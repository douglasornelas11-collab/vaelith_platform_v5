-- Vaelith Labs — núcleo profissional de coordenação e ocorrências
-- Compatível com PostgreSQL/Supabase.

create extension if not exists pgcrypto;

create table if not exists organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists organization_members (
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id text not null,
  role text not null check (role in ('owner','admin','manager','engineer','viewer')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

alter table projects add column if not exists organization_id uuid references organizations(id);
alter table projects add column if not exists status text not null default 'active';
alter table projects add column if not exists updated timestamptz not null default now();

create table if not exists occurrences (
  id uuid primary key default gen_random_uuid(),
  project_id text not null references projects(id) on delete cascade,
  code text not null,
  title text not null,
  description text not null default '',
  category text not null default 'Coordenação',
  severity text not null check (severity in ('Crítica','Alta','Média','Baixa','Informativa')),
  status text not null check (status in ('Nova','Em triagem','Atribuída','Em análise','Aguardando informação','Correção proposta','Correção publicada','Em validação','Resolvida','Aceita tecnicamente','Não procede','Reaberta')),
  evidence_origin text not null check (evidence_origin in ('Geometria 3D','Desenho 2D','Documento','Orçamento','Cronograma','Registro de campo','Entrada manual')),
  detection_method text not null,
  confidence text not null check (confidence in ('Alta','Média','Baixa','Pendente de validação')),
  human_validation_required boolean not null default true,
  human_validation_status text not null default 'Pendente',
  tolerance_mm numeric(12,3),
  location text,
  responsible_name text,
  responsible_user_id text,
  due_date date,
  estimated_cost_impact numeric(16,2),
  estimated_delay_days integer,
  recommended_action text,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(project_id, code)
);

create table if not exists occurrence_files (
  occurrence_id uuid not null references occurrences(id) on delete cascade,
  file_id text not null references files(id) on delete cascade,
  role text not null default 'evidence',
  revision_used text,
  primary key (occurrence_id, file_id, role)
);

create table if not exists occurrence_elements (
  id uuid primary key default gen_random_uuid(),
  occurrence_id uuid not null references occurrences(id) on delete cascade,
  source_file_id text references files(id) on delete set null,
  element_guid text,
  element_type text,
  element_name text,
  discipline_code text,
  geometry_payload jsonb,
  properties jsonb not null default '{}'::jsonb
);

create table if not exists occurrence_evidence (
  id uuid primary key default gen_random_uuid(),
  occurrence_id uuid not null references occurrences(id) on delete cascade,
  evidence_type text not null,
  source_reference text,
  page_number integer,
  excerpt text,
  coordinates jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists occurrence_events (
  id uuid primary key default gen_random_uuid(),
  occurrence_id uuid not null references occurrences(id) on delete cascade,
  event_type text not null,
  actor_user_id text,
  previous_value jsonb,
  new_value jsonb,
  note text,
  created_at timestamptz not null default now()
);

create index if not exists idx_occurrences_project on occurrences(project_id);
create index if not exists idx_occurrences_status on occurrences(project_id, status);
create index if not exists idx_occurrences_severity on occurrences(project_id, severity);
create index if not exists idx_occurrences_origin on occurrences(project_id, evidence_origin);
create index if not exists idx_occurrence_events_occurrence on occurrence_events(occurrence_id, created_at desc);

comment on table occurrences is 'Ocorrências técnicas rastreáveis geradas por BIM, 2D, documentos, orçamento, cronograma, campo ou entrada manual.';
comment on column occurrences.evidence_origin is 'Origem objetiva da evidência, separada do nível de confiança.';
comment on column occurrences.confidence is 'Confiança do resultado, independente do formato de origem.';
