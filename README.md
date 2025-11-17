# 🏂 Парсер лыжных магазинов Грузии

Автоматический сбор, объединение и экспорт данных о лыжах из магазинов **xtreme.ge**, **snowmania.ge**, **burusports.ge** и **megasport.ge**.
Проект собирает товары, извлекает цену, бренд, модель, длины (каждый размер → отдельная строка), и сохраняет данные в единый CSV.

---

## 📁 Структура проекта

```
parsing_ski/
│  README.md
│  requirements.txt
│  run_scrapers.py
│  compare_last_exports.py
│
├─ src/
│   └─ parsing_ski/
│       │  __init__.py
│       │  cli.py
│       │  models.py
│       │  db.py
│       │  export_unified.py
│       │  diff_exports.py
│       │
│       └─ shops/
│           │  shop_extreme_ge.py
│           │  shop_snowmania_ge.py
│           │  shop_burosports_ge.py
│           │  shop_megasport_ge.py
│
├─ data/
│   ├─ db/
│   │    skis.sqlite
│   └─ exports/
│        skis_unified_YYYYMMDD_HHMM.csv
│
└─ logs/
```

---

## 🚀 Установка

```bash
pip install -r requirements.txt
```

---

## 🚀 Запуск

```bash
python run_scrapers.py
```

По умолчанию:
- парсятся **все магазины**
- CSV сохраняется в `data/exports/skis_unified_YYYYMMDD_HHMM.csv`

```bash
python manage_data.py
```
Ищет 2 последних файла с выгрузкой и определяет изменения:
- продано
- новые поступления
- изменение цены

---

## ⚙️ Аргументы командной строки

### `--shops`
```
xtreme snowmania burosports megasport
```
или:
```
--shops all
```

Примеры:
```bash
python run_scrapers.py --shops xtreme snowmania
python run_scrapers.py --shops burosports
python run_scrapers.py --shops all
```

### `--test`
```bash
python run_scrapers.py --test
```

### `--min` / `--max`
```bash
python run_scrapers.py --min 150 --max 190
```

### `--output`
```bash
python run_scrapers.py --output results/myfile.csv
```

---

## 📊 Формат CSV

| № | shops | brand | model | condition | orig_price | price | length_cm | url |

---

## 🛠️ Внутренняя логика

- `cli.py` — аргументы, запуск, объединение данных  
- `shops/*.py` — парсеры магазинов  
- `export_unified.py` — экспорт CSV  
- `models.py` — модель товара 
- `diff_exports.py` - сравнение изменений 

---

## 🧩 Возможные улучшения

- SQLite история цен  
- уведомления о снижении  
- cron-автозапуск  
- графики и аналитика  

---
