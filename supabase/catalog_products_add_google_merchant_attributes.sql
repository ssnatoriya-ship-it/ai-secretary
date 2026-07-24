-- 商品カタログ Google Merchant Center対応強化：color / condition / google_product_category
-- カラム追加のみ（Supabase SQL Editorで手動実行してください。自動実行はしません）。
-- conditionは全商品「新品」前提の店舗のため初期値'new'、google_product_categoryは
-- 主力カテゴリ（革靴・シューズ = Google公式タクソノミーID 187）を初期値とする。
-- ブランドは既存のbrandカラムをそのまま使用するため、新規カラムは追加しない。
-- 既存データへの変更は含まない（ALTER TABLE ADD COLUMN ... DEFAULTにより、
-- 既存行のcondition/google_product_categoryは自動的に初期値で埋まる）。

alter table public.catalog_products
  add column if not exists color text,
  add column if not exists condition text not null default 'new',
  add column if not exists google_product_category text not null default '187';
