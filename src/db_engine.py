import re
import unicodedata


class DatabaseEngine:
    """
    JSONParser tarafından üretilen flat_records ve array_records verilerinden
    dinamik SQLite tablo şeması üretir.

    Çözülen problemler:
    1) JSON içindeki "id" alanı, sistemin otomatik primary key alanıyla çakışmaz.
       Sistem primary key alanı "__record_id" olarak tutulur.
    2) Aynı tablo içinde SQLite açısından çakışabilecek sütun adları otomatik benzersizleştirilir.
       Örnek: "Name" ve "name" aynı tabloda gelirse "name" ve "name_2" olur.
    """

    SYSTEM_PRIMARY_KEY = "__record_id"
    SYSTEM_PARENT_KEY = "__parent_id"
    SYSTEM_VALUE_KEY = "__value"

    def __init__(self):
        self.tables = {}

    def map_python_to_sql_type(self, value):
        """
        Python veri tiplerini SQL veri tiplerine dönüştürür.
        bool kontrolü int kontrolünden önce yapılmalıdır.
        Çünkü Python'da bool, int'in alt türü gibi davranır.
        """
        if value is None:
            return "VARCHAR(255)"
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "INTEGER"
        if isinstance(value, float):
            return "REAL"
        return "VARCHAR(255)"

    def merge_sql_types(self, old_type, new_type):
        """
        Aynı sütun farklı kayıtlarda farklı tipte gelirse güvenli ortak SQL tipi seçer.
        Örneğin INTEGER + REAL => REAL, INTEGER + VARCHAR => VARCHAR.
        """
        if old_type == new_type:
            return old_type

        numeric_types = {"INTEGER", "REAL"}

        if old_type in numeric_types and new_type in numeric_types:
            return "REAL"

        # Primary key kolonunun tipi değiştirilmemelidir.
        if "PRIMARY KEY" in old_type.upper():
            return old_type

        return "VARCHAR(255)"

    def normalize_identifier(self, name, fallback="field"):
        """
        JSON anahtarlarını okunabilir ve güvenli SQL sütun adına dönüştürür.
        SQLite quote kullansak bile büyük JSON'larda case/boşluk/tire kaynaklı
        çakışmaları önlemek için normalize etmek gerekir.
        """
        text = str(name)

        tr_map = str.maketrans({
            "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
            "Ç": "c", "Ğ": "g", "İ": "i", "I": "i", "Ö": "o", "Ş": "s", "Ü": "u",
        })
        text = text.translate(tr_map)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))

        text = text.strip().lower()
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")

        if not text:
            text = fallback

        if text[0].isdigit():
            text = f"{fallback}_{text}"

        return text

    def _make_unique_name(self, preferred_name, used_names):
        """
        SQLite sütun adları case-insensitive çakışabildiği için
        used_names içinde casefold karşılaştırması yapılır.
        """
        base = preferred_name
        candidate = base
        counter = 2

        while candidate.casefold() in used_names:
            candidate = f"{base}_{counter}"
            counter += 1

        used_names.add(candidate.casefold())
        return candidate

    def _add_column(self, columns, column_map, used_names, original_key, value):
        """
        Orijinal JSON key'ini güvenli ve benzersiz SQL sütun adına bağlar.
        Aynı orijinal key tekrar gelirse aynı sütuna yazılır.
        """
        if original_key in column_map:
            column_name = column_map[original_key]
            columns[column_name] = self.merge_sql_types(
                columns[column_name],
                self.map_python_to_sql_type(value)
            )
            return column_name

        preferred = self.normalize_identifier(original_key)

        # Sistem kolonlarıyla çakışırsa JSON alanını ayrı isimle sakla.
        if preferred in {
            self.SYSTEM_PRIMARY_KEY,
            self.SYSTEM_PARENT_KEY,
            self.SYSTEM_VALUE_KEY
        }:
            preferred = f"json_{preferred.strip('_')}"

        column_name = self._make_unique_name(preferred, used_names)
        column_map[original_key] = column_name
        columns[column_name] = self.map_python_to_sql_type(value)
        return column_name

    def build_schema(self, table_name, flat_records, array_records):
        """
        Düzleştirilmiş verileri okuyarak ana tablo ve alt tabloların
        sütunlarını, veri tiplerini ve ilişkilerini dinamik olarak tasarlar.
        """
        self.tables = {}

        if not flat_records:
            return self.tables

        # 1. ANA TABLO TASARIMI
        main_columns = {
            self.SYSTEM_PRIMARY_KEY: "INTEGER PRIMARY KEY AUTOINCREMENT"
        }
        main_column_map = {}
        main_used_names = {self.SYSTEM_PRIMARY_KEY.casefold()}

        for record in flat_records:
            for key, value in record.items():
                self._add_column(
                    columns=main_columns,
                    column_map=main_column_map,
                    used_names=main_used_names,
                    original_key=key,
                    value=value
                )

        self.tables[table_name] = {
            "columns": main_columns,
            "foreign_keys": [],
            "column_map": main_column_map,
            "primary_key": self.SYSTEM_PRIMARY_KEY,
        }

        # 2. ALT TABLO / ARRAY TASARIMI
        all_array_keys = set()

        for arrays in array_records:
            for array_key in arrays.keys():
                all_array_keys.add(array_key)

        for array_key in sorted(all_array_keys):
            child_table_name = f"{table_name}_{array_key}"

            child_columns = {
                self.SYSTEM_PRIMARY_KEY: "INTEGER PRIMARY KEY AUTOINCREMENT",
                self.SYSTEM_PARENT_KEY: "INTEGER"
            }
            child_column_map = {}
            child_used_names = {
                self.SYSTEM_PRIMARY_KEY.casefold(),
                self.SYSTEM_PARENT_KEY.casefold(),
            }

            all_items = []

            for arrays in array_records:
                array_list = arrays.get(array_key, [])
                if isinstance(array_list, list):
                    all_items.extend(array_list)

            value_column_name = None

            for item in all_items:
                if isinstance(item, dict):
                    for sub_key, sub_val in item.items():
                        self._add_column(
                            columns=child_columns,
                            column_map=child_column_map,
                            used_names=child_used_names,
                            original_key=sub_key,
                            value=sub_val
                        )
                else:
                    if value_column_name is None:
                        preferred = self.normalize_identifier("value")
                        value_column_name = self._make_unique_name(
                            preferred,
                            child_used_names
                        )
                        child_columns[value_column_name] = self.map_python_to_sql_type(item)
                    else:
                        child_columns[value_column_name] = self.merge_sql_types(
                            child_columns[value_column_name],
                            self.map_python_to_sql_type(item)
                        )

            self.tables[child_table_name] = {
                "columns": child_columns,
                "foreign_keys": [
                    f"FOREIGN KEY({self.SYSTEM_PARENT_KEY}) REFERENCES {table_name}({self.SYSTEM_PRIMARY_KEY})"
                ],
                "column_map": child_column_map,
                "primary_key": self.SYSTEM_PRIMARY_KEY,
                "parent_key": self.SYSTEM_PARENT_KEY,
                "value_column": value_column_name or "value",
                "source_array_key": array_key,
            }

        return self.tables