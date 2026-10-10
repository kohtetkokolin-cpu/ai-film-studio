create extension if not exists pgcrypto;

create table public.film_projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 160),
  genre text not null default 'Drama',
  duration_seconds integer not null check (duration_seconds between 8 and 300),
  visual_style text not null default 'Realistic cinematic',
  workflow text not null default 'automatic',
  aspect_ratio text not null default '16:9',
  language text not null default 'Burmese',
  story_idea text not null,
  character_bible text not null default '',
  location_bible text not null default '',
  continuity_notes text not null default '',
  clips jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.film_projects enable row level security;

create policy "Read own film projects"
on public.film_projects for select to authenticated
using (auth.uid() = user_id);

create policy "Insert own film projects"
on public.film_projects for insert to authenticated
with check (auth.uid() = user_id);

create policy "Update own film projects"
on public.film_projects for update to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "Delete own film projects"
on public.film_projects for delete to authenticated
using (auth.uid() = user_id);

create index film_projects_user_updated_idx
on public.film_projects (user_id, updated_at desc);

grant select, insert, update, delete on public.film_projects to authenticated;
