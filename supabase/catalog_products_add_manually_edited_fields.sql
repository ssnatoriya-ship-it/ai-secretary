-- 手動編集項目のAI再生成時保護（manual-edit-protection）
-- Supabase SQL Editorで手動実行してください。
-- 既存の catalog_products テーブルへの列追加のみ。他の列・他のテーブルへの変更は含まない。
-- field_review_status（未使用・将来の採用/修正採用/不採用レビュー機構向けに予約済み）とは
-- 意図的に分離し、今回の単純な「手動編集済みフラグ」専用の列として新設する
-- （catalog-production-manual-edit-protection-investigation.md参照）。
--
-- 保存する内容：{ seoTitle: true/false, seoDescription: true/false, description1Body: true/false,
-- description2Body: true/false, description3Body: true/false } のうち、手動編集された項目のみ
-- true を持つオブジェクト。編集可能な5項目以外は対象外。既存データは空オブジェクト{}のまま
-- （＝すべて未編集）として扱われ、後方互換性の問題はない。

alter table public.catalog_products
  add column if not exists manually_edited_fields jsonb not null default '{}'::jsonb;
