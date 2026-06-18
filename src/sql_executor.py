import sqlite3
import re
import json


class SQLExecutor:
    def __init__(self, db_name="dynamic_nosql.db"):
        # Varsayılan olarak proje dizininde bir SQLite dosyası oluşturur.
        self.db_name = db_name

    def quote_identifier(self, name):
        """
        Tablo ve sütun isimlerini SQLite için güvenli hale getirir.
        Boşluk, tire, Türkçe karakter veya reserved keyword olsa bile çalışır.
        """
        safe_name = str(name).replace('"', '""')
        return f'"{safe_name}"'

    def format_foreign_key(self, fk_text):
        """
        DatabaseEngine tarafından üretilen foreign key metnini güvenli quoted hale getirir.

        Girdi:
        FOREIGN KEY(__parent_id) REFERENCES main(__record_id)

        Çıktı:
        FOREIGN KEY("__parent_id") REFERENCES "main"("__record_id")
        """
        pattern = r"FOREIGN KEY\((.*?)\)\s+REFERENCES\s+(.*?)\((.*?)\)"
        match = re.match(pattern, fk_text.strip(), re.IGNORECASE)

        if not match:
            return fk_text

        fk_column = match.group(1).strip()
        ref_table = match.group(2).strip()
        ref_column = match.group(3).strip()

        return (
            f"FOREIGN KEY({self.quote_identifier(fk_column)}) "
            f"REFERENCES {self.quote_identifier(ref_table)}({self.quote_identifier(ref_column)})"
        )

    def adapt_value(self, value):
        """
        SQLite'ın doğrudan yazamadığı dict/list gibi değerleri JSON string'e çevirir.
        Normal parser çoğu yapıyı düzleştirir; bu metot ekstra güvenlik sağlar.
        """
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)

        if isinstance(value, bool):
            return int(value)

        return value

    def transform_record_by_schema(self, record, table_info):
        """
        Orijinal JSON key'lerini DatabaseEngine'in ürettiği güvenli sütun adlarına dönüştürür.
        """
        column_map = table_info.get("column_map", {})
        transformed = {}

        for original_key, value in record.items():
            column_name = column_map.get(original_key, original_key)
            transformed[column_name] = self.adapt_value(value)

        return transformed

    def execute_schema(self, schema_dict):
        """
        Üretilen sanal tablo taslaklarını gerçek SQL CREATE TABLE komutlarına dönüştürür.
        """
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("PRAGMA foreign_keys = ON;")

        for table_name, table_info in schema_dict.items():
            columns = []

            for col_name, col_type in table_info["columns"].items():
                quoted_col = self.quote_identifier(col_name)
                columns.append(f"{quoted_col} {col_type}")

            if "foreign_keys" in table_info and table_info["foreign_keys"]:
                for fk in table_info["foreign_keys"]:
                    columns.append(self.format_foreign_key(fk))

            columns_sql = ", ".join(columns)
            quoted_table = self.quote_identifier(table_name)

            create_query = f"CREATE TABLE IF NOT EXISTS {quoted_table} ({columns_sql});"
            cursor.execute(create_query)

        conn.commit()
        conn.close()

    def insert_data(self, main_table_name, flat_records, array_records, schema_dict=None):
        """
        Ayrıştırılan verileri veritabanındaki ilgili tablolara INSERT komutlarıyla ekler.

        schema_dict parametresi önemlidir:
        - id çakışmasını engelleyen __record_id alanını dikkate alır.
        - Duplicate/case-insensitive sütun isimlerini column_map ile doğru sütuna yazar.
        """
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("PRAGMA foreign_keys = ON;")

        quoted_main_table = self.quote_identifier(main_table_name)
        main_table_info = schema_dict.get(main_table_name, {}) if schema_dict else {}

        for i, record in enumerate(flat_records):
            # 1. Ana tabloya veri ekleme
            transformed_record = (
                self.transform_record_by_schema(record, main_table_info)
                if schema_dict else record
            )

            if transformed_record:
                columns = ", ".join(
                    [self.quote_identifier(col) for col in transformed_record.keys()]
                )
                placeholders = ", ".join(["?" for _ in transformed_record])
                values = tuple(self.adapt_value(v) for v in transformed_record.values())

                insert_main_query = (
                    f"INSERT INTO {quoted_main_table} ({columns}) "
                    f"VALUES ({placeholders});"
                )
                cursor.execute(insert_main_query, values)
            else:
                insert_main_query = f"INSERT INTO {quoted_main_table} DEFAULT VALUES;"
                cursor.execute(insert_main_query)

            main_id = cursor.lastrowid

            # 2. Alt tablolara veri ekleme
            if array_records and i < len(array_records):
                arrays = array_records[i]

                for array_key, array_list in arrays.items():
                    child_table_name = f"{main_table_name}_{array_key}"
                    quoted_child_table = self.quote_identifier(child_table_name)
                    child_table_info = schema_dict.get(child_table_name, {}) if schema_dict else {}

                    parent_key = child_table_info.get("parent_key", f"{main_table_name}_id")
                    value_column = child_table_info.get("value_column", "deger")

                    for item in array_list:
                        if isinstance(item, dict):
                            item_to_insert = (
                                self.transform_record_by_schema(item, child_table_info)
                                if schema_dict else dict(item)
                            )
                            item_to_insert[parent_key] = main_id

                            child_cols = ", ".join(
                                [self.quote_identifier(col) for col in item_to_insert.keys()]
                            )
                            child_placeholders = ", ".join(["?" for _ in item_to_insert])
                            child_values = tuple(
                                self.adapt_value(v) for v in item_to_insert.values()
                            )

                        else:
                            child_cols = (
                                f"{self.quote_identifier(parent_key)}, "
                                f"{self.quote_identifier(value_column)}"
                            )
                            child_placeholders = "?, ?"
                            child_values = (main_id, self.adapt_value(item))

                        insert_child_query = (
                            f"INSERT INTO {quoted_child_table} ({child_cols}) "
                            f"VALUES ({child_placeholders});"
                        )
                        cursor.execute(insert_child_query, child_values)

        conn.commit()
        conn.close()

    def drop_all_tables(self):
        """
        Sistemi sıfırlamak için veritabanındaki tüm kullanıcı tablolarını siler.
        """
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute("PRAGMA foreign_keys = OFF;")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()

        for table in tables:
            table_name = table[0]

            if table_name != "sqlite_sequence":
                quoted_table = self.quote_identifier(table_name)
                cursor.execute(f"DROP TABLE IF EXISTS {quoted_table};")

        conn.commit()

        cursor.execute("PRAGMA foreign_keys = ON;")
        conn.close()

    def get_schema_sql(self, schema_dict):
        """
        Arayüzde göstermek üzere dinamik SQL CREATE TABLE komutlarını metin olarak üretir.
        """
        sql_script = "-- DİNAMİK OLARAK ÜRETİLEN SQL ŞEMASI --\n\n"

        for table_name, table_info in schema_dict.items():
            columns = []

            for col_name, col_type in table_info["columns"].items():
                quoted_col = self.quote_identifier(col_name)
                columns.append(f"{quoted_col} {col_type}")

            if "foreign_keys" in table_info and table_info["foreign_keys"]:
                for fk in table_info["foreign_keys"]:
                    columns.append(self.format_foreign_key(fk))

            columns_sql = ",\n    ".join(columns)
            quoted_table = self.quote_identifier(table_name)

            create_query = (
                f"CREATE TABLE {quoted_table} (\n"
                f"    {columns_sql}\n"
                f");\n\n"
            )

            sql_script += create_query

        return sql_script