class JSONParser:
    def __init__(self):
        pass

    def parse_and_flatten(self, data):
        """
        Gelen JSON verisini işler.
        Eğer veri liste ise her bir elemanı ayrı ana kayıt olarak işler.
        Eğer veri tek obje ise tek ana kayıt üretir.

        Çıktı:
        - flat_records: ana tabloya gidecek düzleştirilmiş kayıtlar
        - array_records: alt tablolara gidecek array verileri
        """
        flat_records = []
        array_records = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    flat_data, arrays = self._flatten_dict(item)
                    flat_records.append(flat_data)
                    array_records.append(arrays)
                else:
                    # Kök liste basit değerlerden oluşuyorsa
                    flat_records.append({"deger": item})
                    array_records.append({})

        elif isinstance(data, dict):
            flat_data, arrays = self._flatten_dict(data)
            flat_records.append(flat_data)
            array_records.append(arrays)

        else:
            # Kök veri doğrudan string/int/bool gibi basit değer ise
            flat_records.append({"deger": data})
            array_records.append({})

        return flat_records, array_records

    def _merge_arrays(self, target, source):
        """
        Array sözlüklerini güvenli şekilde birleştirir.
        Aynı array_key tekrar gelirse üzerine yazmaz, listeyi uzatır.
        """
        for key, value in source.items():
            if key not in target:
                target[key] = []

            if isinstance(value, list):
                target[key].extend(value)
            else:
                target[key].append(value)

    def _flatten_dict(self, d, parent_key='', sep='_'):
        """
        İç içe geçmiş dict yapılarını parent_child formatında düzleştirir.
        Array yapıları ise ayrı alt tablo verisi olarak arrays içine alınır.
        """
        items = {}
        arrays = {}

        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k

            if isinstance(v, dict):
                sub_items, sub_arrays = self._flatten_dict(v, new_key, sep=sep)
                items.update(sub_items)
                self._merge_arrays(arrays, sub_arrays)

            elif isinstance(v, list):
                normalized_items, nested_arrays = self._normalize_array(new_key, v, sep=sep)
                arrays[new_key] = normalized_items
                self._merge_arrays(arrays, nested_arrays)

            else:
                items[new_key] = v

        return items, arrays

    def _normalize_array(self, array_key, array_list, sep='_'):
        """
        Array içindeki elemanları SQL'e uygun hale getirir.

        Örnek:
        "items": [
            {
                "name": "A",
                "detail": {"x": 5}
            }
        ]

        Şuna dönüşür:
        items tablosu:
            name
            detail_x

        Eğer array item içinde tekrar array varsa:
        "items": [
            {
                "name": "A",
                "tags": ["x", "y"]
            }
        ]

        Şuna dönüşür:
        items tablosu:
            name

        items_tags tablosu:
            items_index
            deger
        """
        normalized_items = []
        nested_arrays = {}

        for index, item in enumerate(array_list):
            if isinstance(item, dict):
                flat_item, sub_arrays = self._flatten_dict(item, parent_key='', sep=sep)

                # Nested array'leri ana array elemanına bağlayabilmek için index ekliyoruz.
                for sub_array_key, sub_array_items in sub_arrays.items():
                    nested_key = f"{array_key}{sep}{sub_array_key}"

                    if nested_key not in nested_arrays:
                        nested_arrays[nested_key] = []

                    for sub_item in sub_array_items:
                        if isinstance(sub_item, dict):
                            new_sub_item = dict(sub_item)
                            new_sub_item[f"{array_key}_index"] = index
                            nested_arrays[nested_key].append(new_sub_item)
                        else:
                            nested_arrays[nested_key].append({
                                f"{array_key}_index": index,
                                "deger": sub_item
                            })

                normalized_items.append(flat_item)

            elif isinstance(item, list):
                # Array içinde array varsa her elemanı ayrı satır yapıyoruz.
                nested_key = f"{array_key}{sep}items"

                if nested_key not in nested_arrays:
                    nested_arrays[nested_key] = []

                for sub_index, sub_item in enumerate(item):
                    if isinstance(sub_item, dict):
                        flat_sub_item, deeper_arrays = self._flatten_dict(sub_item, parent_key='', sep=sep)
                        flat_sub_item[f"{array_key}_index"] = index
                        flat_sub_item[f"{array_key}_sub_index"] = sub_index
                        nested_arrays[nested_key].append(flat_sub_item)
                        self._merge_arrays(nested_arrays, deeper_arrays)
                    else:
                        nested_arrays[nested_key].append({
                            f"{array_key}_index": index,
                            f"{array_key}_sub_index": sub_index,
                            "deger": sub_item
                        })

            else:
                # Basit değerlerden oluşan array: ["A", "B", "C"]
                normalized_items.append(item)

        return normalized_items, nested_arrays