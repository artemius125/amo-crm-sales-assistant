PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('product','policy')),
  source TEXT NOT NULL,
  reviewed_at TEXT NOT NULL,
  product_id TEXT
);
CREATE TABLE IF NOT EXISTS product_aliases (
  product_id TEXT NOT NULL,
  alias TEXT NOT NULL,
  PRIMARY KEY (product_id, alias)
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  product_id TEXT,
  category TEXT NOT NULL,
  value TEXT NOT NULL,
  volatile INTEGER NOT NULL DEFAULT 0 CHECK (volatile IN (0,1))
);
CREATE INDEX IF NOT EXISTS facts_lookup ON facts(product_id, category);
CREATE TABLE IF NOT EXISTS upsell_rules (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  add_on_id TEXT NOT NULL REFERENCES documents(id),
  reason TEXT NOT NULL,
  question TEXT NOT NULL,
  trigger_terms TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

-- Учебные данные; цены, остатки и условия вымышлены.
INSERT OR IGNORE INTO documents VALUES
 ('laptop','Ноутбук Office 14','Ноутбук Office 14 для офисной работы. Цена, наличие, гарантия, HDMI и USB-C.','product','demo://catalog/laptop','2026-09-29','laptop'),
 ('monitor','Монитор View 27','Монитор View 27 с HDMI, диагональю 27 дюймов. Цена и гарантия.','product','demo://catalog/monitor','2026-09-29','monitor'),
 ('dock','Док-станция Connect 6','Док-станция Connect 6 с USB-C, HDMI и USB-A. Цена и гарантия.','product','demo://catalog/dock','2026-09-29','dock'),
 ('delivery-moscow','Доставка по Москве','Условия доставки по Москве, срок после подтверждения заказа.','policy','demo://policies/delivery','2026-09-29',NULL),
 ('delivery-russia','Доставка по России','Условия доставки в другие города России, срок после подтверждения заказа.','policy','demo://policies/delivery','2026-09-29',NULL),
 ('corporate','Корпоративный заказ','Заказ нескольких устройств для офиса, счёт, реквизиты, коммерческое предложение.','policy','demo://policies/corporate','2026-09-29',NULL),
 ('payment','Оплата','Оплата заказа и выставление счёта юридическому лицу.','policy','demo://policies/payment','2026-09-29',NULL),
 ('returns','Возврат и претензия','Возврат товара, проблема, неисправность, претензия.','policy','demo://policies/returns','2026-09-29',NULL);

INSERT OR IGNORE INTO product_aliases VALUES
 ('laptop','ноутбук'),('laptop','ноутбуки'),('laptop','Office 14'),
 ('monitor','монитор'),('monitor','мониторы'),('monitor','View 27'),
 ('dock','док-станция'),('dock','докстанция'),('dock','Connect 6');

INSERT OR IGNORE INTO facts VALUES
 ('laptop-price','laptop','laptop','price','59 900 ₽ за штуку',1),
 ('laptop-stock','laptop','laptop','stock','12 штук',1),
 ('laptop-warranty','laptop','laptop','warranty','24 месяца',0),
 ('laptop-ports','laptop','laptop','ports','HDMI и USB-C',0),
 ('monitor-price','monitor','monitor','price','19 900 ₽ за штуку',1),
 ('monitor-warranty','monitor','monitor','warranty','24 месяца',0),
 ('monitor-ports','monitor','monitor','ports','HDMI',0),
 ('monitor-size','monitor','monitor','size','27 дюймов',0),
 ('dock-price','dock','dock','price','7 900 ₽ за штуку',1),
 ('dock-warranty','dock','dock','warranty','12 месяцев',0),
 ('dock-ports','dock','dock','ports','USB-C, HDMI и USB-A',0),
 ('delivery-moscow-time','delivery-moscow',NULL,'delivery_moscow','1–2 рабочих дня после подтверждения заказа',1),
 ('delivery-russia-time','delivery-russia',NULL,'delivery_russia','3–7 рабочих дней после подтверждения заказа',1),
 ('payment-corporate','payment',NULL,'payment','для юридического лица можно выставить счёт; оплата после подтверждения заказа',0),
 ('corporate-order','corporate',NULL,'corporate','количество, город доставки и реквизиты организации',0),
 ('return-process','returns',NULL,'return','для проверки возврата нужны номер заказа и описание ситуации',0);

INSERT OR IGNORE INTO upsell_rules VALUES
 ('laptop-monitor','laptop','monitor','Внешний монитор с HDMI может помочь, когда клиенту тесно на одном экране или он одновременно работает в нескольких окнах.','Бывает, что на экране ноутбука не помещаются все нужные окна?','много таблиц,несколько окон,второй экран,переключаться,мало места',100,1),
 ('monitor-dock','monitor','dock','Док-станция с HDMI и USB-A может помочь подключить периферию.','Нужна ли док-станция для подключения монитора и периферии?','подключение,периферия,ноутбук',80,1);
