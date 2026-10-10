-- Additive schema update: preserves existing projects and clip data.
alter table public.film_projects
  add column if not exists culture text not null default 'Myanmar',
  add column if not exists generation_mode text not null default 'auto'
    check (generation_mode in ('template', 'gemini', 'auto')),
  add column if not exists sound_mode text not null default 'dialogue',
  add column if not exists production_package jsonb not null default '{}'::jsonb;

comment on column public.film_projects.generation_mode is
  'template = no Gemini API; gemini = require Gemini; auto = Gemini with rules-based template fallback.';
comment on column public.film_projects.production_package is
  'Versioned story analysis, character/location/prop bibles, scene plan, and quality report.';
