-- ChatGPT調査結果・確定情報を保存する列を追加する
-- Supabase SQL Editorで手動実行してください。
-- 既存の catalog_products テーブルへの列追加のみ。他の列・他のテーブルへの変更は含まない。
--
-- 既存フィールド（known_specs・supplementary_info・reference_urls・research_notes_input）は
-- いずれも用途が異なる既存項目（店舗側の既知スペック・補足情報・参考URL・調査時の注意事項）であり、
-- ChatGPTで調査した結果をまとめて貼り付けるための自由記述欄としては流用しない
-- （catalog-edit-chatgpt-research-workflow-redesign-report.md参照）。
--
-- 保存する内容：ChatGPTで商品写真・情報元URLを調査した結果を、そのまま自由文で貼り付けたもの。
-- カタログ原稿生成プロンプトにおいて最優先の確定情報として扱う。
-- 未設定の既存商品は空文字として扱われ、後方互換性の問題はない。

alter table public.catalog_products
  add column if not exists chatgpt_research_result text not null default '';
