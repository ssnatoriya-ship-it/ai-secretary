-- 商品カタログ Google Merchant CSV出力用：公開画像URL手動入力欄のDBカラム追加のみ
-- （Supabase SQL Editorで手動実行してください。自動実行はしません）。
-- Supabase Storageの商品画像は非公開バケットの署名付きURLであり、Google Merchant Centerの
-- 画像リンクには使用できないため、外部から常時アクセス可能な公開画像URLを別途保存する
-- （catalog-merchant-image-url-report.md参照）。既存データへの変更は含まない。

alter table public.catalog_products
  add column if not exists merchant_image_url text;
