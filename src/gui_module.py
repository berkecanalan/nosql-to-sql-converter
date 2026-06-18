import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json
import os
import sqlite3

try:
    from .parser_module import JSONParser
    from .db_engine import DatabaseEngine
    from .sql_executor import SQLExecutor
except ImportError:
    from parser_module import JSONParser
    from db_engine import DatabaseEngine
    from sql_executor import SQLExecutor


class NoSQLtoSQLConverterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NoSQL'den SQL'e Dönüşüm Sistemi")
        self.root.geometry("900x650")

        self.current_schema = None
        self.setup_ui()

    def setup_ui(self):
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        self.load_btn = tk.Button(
            btn_frame,
            text="JSON Dosyası Yükle",
            command=self.load_json
        )
        self.load_btn.pack(side=tk.LEFT, padx=8)

        self.show_db_btn = tk.Button(
            btn_frame,
            text="Veritabanını Görüntüle",
            command=self.show_database
        )
        self.show_db_btn.pack(side=tk.LEFT, padx=8)

        self.show_sql_btn = tk.Button(
            btn_frame,
            text="SQL Şemasını Göster",
            command=self.show_sql_schema
        )
        self.show_sql_btn.pack(side=tk.LEFT, padx=8)

        self.reset_btn = tk.Button(
            btn_frame,
            text="Sistemi Sıfırla",
            command=self.reset_system
        )
        self.reset_btn.pack(side=tk.LEFT, padx=8)

        self.text_area = tk.Text(self.root, wrap=tk.WORD, font=("Menlo", 12))
        self.text_area.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)

    def database_has_tables(self, db_path="dynamic_nosql.db"):
        """
        Veritabanında kullanıcı tablosu var mı kontrol eder.
        sqlite_sequence sistem tablosu dikkate alınmaz.
        """
        if not os.path.exists(db_path):
            return False

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name != 'sqlite_sequence';"
        )
        tables = cursor.fetchall()

        conn.close()
        return len(tables) > 0

    def load_json(self):
        filepath = filedialog.askopenfilename(
            title="Bir JSON dosyası seçin",
            filetypes=[("JSON Dosyaları", "*.json")]
        )

        if not filepath:
            return

        try:
            executor = SQLExecutor()

            # Eski verilerin üst üste birikmesini önlemek için kullanıcıya sorulur.
            if self.database_has_tables():
                should_reset = messagebox.askyesno(
                    "Veritabanı Temizlensin mi?",
                    "Veritabanında daha önce oluşturulmuş tablolar var.\n\n"
                    "Yeni JSON dosyasını temiz bir veritabanına aktarmak ister misiniz?\n\n"
                    "Evet: Eski tablolar silinir ve yeni JSON temiz şekilde aktarılır.\n"
                    "Hayır: Yeni veri mevcut veritabanına eklenmeye çalışılır."
                )

                if should_reset:
                    executor.drop_all_tables()

            with open(filepath, "r", encoding="utf-8") as file:
                data = json.load(file)

            formatted_json = json.dumps(data, indent=4, ensure_ascii=False)

            self.text_area.delete(1.0, tk.END)
            self.text_area.insert(tk.END, formatted_json)

            parser = JSONParser()
            flat_records, array_records = parser.parse_and_flatten(data)

            filename = os.path.splitext(os.path.basename(filepath))[0]

            engine = DatabaseEngine()
            schema = engine.build_schema(filename, flat_records, array_records)
            self.current_schema = schema

            executor.execute_schema(schema)

            # ÖNEMLİ:
            # Artık insert_data metoduna schema da gönderiyoruz.
            # Böylece id çakışmaları ve benzersizleştirilmiş sütun adları doğru eşleşiyor.
            executor.insert_data(filename, flat_records, array_records, schema)

            messagebox.showinfo(
                "Başarılı",
                "Veriler başarıyla analiz edildi ve SQL veritabanına aktarıldı!\n\n"
                f"Ana Tablo: {filename}"
            )

        except Exception as e:
            messagebox.showerror(
                "Hata",
                f"İşlem sırasında hata oluştu:\n{str(e)}"
            )

    def show_database(self):
        db_path = "dynamic_nosql.db"

        if not os.path.exists(db_path):
            messagebox.showwarning("Uyarı", "Henüz oluşturulmuş bir veritabanı yok.")
            return

        executor = SQLExecutor()

        db_window = tk.Toplevel(self.root)
        db_window.title("Veritabanı Tabloları")
        db_window.geometry("1000x650")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name != 'sqlite_sequence';"
        )
        tables = cursor.fetchall()

        if not tables:
            conn.close()
            tk.Label(db_window, text="Veritabanı boş.").pack(pady=20)
            return

        notebook = ttk.Notebook(db_window)
        notebook.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

        for table in tables:
            table_name = table[0]
            quoted_table_name = executor.quote_identifier(table_name)

            frame = ttk.Frame(notebook)
            notebook.add(frame, text=table_name)

            cursor.execute(f"PRAGMA table_info({quoted_table_name});")
            columns = [col[1] for col in cursor.fetchall()]

            tree = ttk.Treeview(frame, columns=columns, show="headings")

            for col in columns:
                tree.heading(col, text=col)
                tree.column(col, width=160, anchor="center")

            y_scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            x_scrollbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)

            tree.configure(
                yscrollcommand=y_scrollbar.set,
                xscrollcommand=x_scrollbar.set
            )

            y_scrollbar.pack(side="right", fill="y")
            x_scrollbar.pack(side="bottom", fill="x")
            tree.pack(expand=True, fill=tk.BOTH)

            cursor.execute(f"SELECT * FROM {quoted_table_name};")
            rows = cursor.fetchall()

            for row in rows:
                tree.insert("", tk.END, values=row)

        conn.close()

    def show_sql_schema(self):
        if self.current_schema:
            executor = SQLExecutor()
            sql_text = executor.get_schema_sql(self.current_schema)

            sql_window = tk.Toplevel(self.root)
            sql_window.title("Üretilen SQL Şeması")
            sql_window.geometry("750x550")

            text_area = tk.Text(
                sql_window,
                wrap=tk.WORD,
                font=("Menlo", 12),
                bg="#1e1e1e",
                fg="#d4d4d4"
            )
            text_area.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
            text_area.insert(tk.END, sql_text)
        else:
            messagebox.showwarning(
                "Uyarı",
                "Lütfen önce bir JSON dosyası yükleyin."
            )

    def reset_system(self):
        self.text_area.delete(1.0, tk.END)

        executor = SQLExecutor()
        executor.drop_all_tables()

        self.current_schema = None

        messagebox.showinfo(
            "Sıfırlandı",
            "Arayüz ve veritabanındaki tüm tablolar başarıyla temizlendi."
        )