-- 商品カタログ Google Merchant Center対応強化：availability（在庫状況）カラム追加
-- カラム追加のみ（Supabase SQL Editorで手動実行してください。自動実行はしません）。
-- Google Merchant CSVの「在庫状況」列は現在すべて固定値'in_stock'を出力しているが、
-- 実際の在庫状況を保存できるようこのカラムを新設する（catalog-google-merchant-availability-report.md参照）。
-- 初期値'in_stock'のため、既存データへの実質的な変更は含まない（既存商品も現状と同じ
-- 'in_stock'として扱われる。実際の在庫状況への更新は店舗側の手動対応に委ねる）。

alter table public.catalog_products
  add column if not exists availability text not null default 'in_stock';
