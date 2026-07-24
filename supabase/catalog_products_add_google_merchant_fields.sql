-- 商品カタログ Google Merchant Center連携 Phase1: DBカラム追加のみ
-- （Supabase SQL Editorで手動実行してください。自動実行はしません）。
-- 今回はGoogle Merchant Centerとの実連携（フィード生成・送信・API連携等）は一切行わない。
-- 販売価格・Google掲載予定フラグの保存先を用意するだけ
-- （catalog-google-merchant-center-phase1-report.md参照）。既存カラムへの変更は含まない。

alter table public.catalog_products
  add column if not exists price_jpy integer,
  add column if not exists google_publish boolean not null default false;
