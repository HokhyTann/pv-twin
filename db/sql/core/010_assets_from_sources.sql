-- Assets that the source data refers to. Phase 2 (jobs.layout_gen) adds the rest of the
-- electrical tree (transformers, combiners, tables) and all geometry.
-- Upserts only: re-running never changes asset_id, so clean/mart keys stay stable.

-- Fleet inverters (high dataset): site comes from the file's site code.
insert into core.asset (site_id, asset_type, code)
select distinct s.site_id, 'inverter', btrim(r.inverter_id)
from raw.high_inverter_daily r
join core.site s on s.source_dataset = 'high' and s.source_code = btrim(r.site)
where r.inverter_id is not null
on conflict (site_id, code) do nothing;

-- PV-06 inverters with nameplate data from the asset register.
insert into core.asset (site_id, asset_type, code, attrs)
select s.site_id, 'inverter', btrim(r.inverter_id),
       jsonb_strip_nulls(jsonb_build_object(
         'model',        r.model,
         'rated_ac_kw',  clean.try_num(r.rated_ac_kw),
         'dc_kwp',       clean.try_num(r.dc_capacity_kwp),
         'commissioned', clean.try_date(r.commissioned)))
from raw.expert_asset_register r
cross join (select site_id from core.site where source_dataset = 'expert') s
where r.inverter_id is not null
on conflict (site_id, code) do update set attrs = core.asset.attrs || excluded.attrs;

-- PV-06 revenue meter at the substation (billing basis).
insert into core.asset (site_id, asset_type, code, attrs)
select site_id, 'meter', 'MTR-01',
       '{"role": "revenue", "counterparty": "EDC", "accuracy_class": "0.2S"}'::jsonb
from core.site where source_dataset = 'expert'
on conflict (site_id, code) do nothing;
