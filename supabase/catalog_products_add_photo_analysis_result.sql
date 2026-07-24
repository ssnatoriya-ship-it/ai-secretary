-- Phase3-A3: 商品写真の画像解析結果を再表示できるように保存する列を追加する
-- Supabase SQL Editorで手動実行してください。
-- 既存の catalog_products テーブルへの列追加のみ。他の列・他のテーブルへの変更は含まない。
--
-- 保存する内容：確認/推定/要検証の各項目・写真ごとの観察結果・入力情報との矛盾警告・
-- 写り込み警告・注意事項・解析対象枚数・解析日時をひとまとめにしたjsonbオブジェクト。
-- spec_data等（AI原稿生成用の列）とは独立しており、写真解析（Phase3-A3）専用の列。
-- 再解析のたびに最新の結果で上書きする想定（履歴は残さない）。
-- （catalog-production-phase3a3-photo-analysis-persistence-report.md参照）

alter table public.catalog_products
  add column if not exists photo_analysis_result jsonb not null default '{}'::jsonb;
