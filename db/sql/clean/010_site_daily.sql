-- clean.site_daily from the low (3 sites) and medium (1 site) datasets.

create temp table stg_site_daily on commit drop as
with src as (
  select 'low_site_daily'::text as source_table, r._row, s.site_id, s.site_code,
         s.capacity_dc_kwp                          as reg_kwp,
         clean.try_date(r.date)                     as day,
         clean.try_num(r.capacity_mwp) * 1000       as file_kwp,
         clean.try_num(r.energy_mwh)                as e,
         clean.try_num(r.irradiation_kwh_m2)        as i,
         null::numeric                              as amb,
         clean.try_num(r.availability_pct)          as a,
         null::boolean                              as cleaned,
         r.energy_mwh as raw_e, r.irradiation_kwh_m2 as raw_i, r.availability_pct as raw_a
  from raw.low_site_daily r
  join core.site s on s.source_dataset = 'low' and s.source_code = btrim(r.site)
  union all
  select 'medium_site_daily', r._row, s.site_id, s.site_code, s.capacity_dc_kwp,
         clean.try_date(r.date), null, clean.try_num(r.energy_mwh),
         clean.try_num(r.irradiation_kwh_m2), clean.try_num(r.ambient_max_c), null,
         btrim(r.panel_cleaning) = '1',
         r.energy_mwh, r.irradiation_kwh_m2, null
  from raw.medium_site_daily r
  join core.site s on s.source_dataset = 'medium' and s.source_code = ''
)
select *,
       row_number() over (partition by site_id, day order by _row) as rn,
       first_value(_row) over (partition by site_id, day order by _row) as first_row,
       coalesce(reg_kwp, file_kwp) / 1000.0 as cap_mwp
from src;

-- Rows with an unreadable date cannot be placed in time: log and drop.
insert into clean.dq_issue (source_table, rule, severity, source_row, entity, detail, action)
select source_table, 'invalid_date', 'error', _row, site_code,
       'date could not be parsed', 'row dropped'
from stg_site_daily where day is null;

-- Duplicates: keep the first line, log the rest (and whether values differ).
insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select d.source_table, 'duplicate_row', 'warn', d._row, d.site_code, d.day, d.day,
       format('same site and date as line %s; values %s', d.first_row,
              case when (d.e, d.i, d.a, d.amb) is not distinct from (f.e, f.i, f.a, f.amb)
                   then 'identical' else 'differ' end),
       format('dropped (line %s kept)', d.first_row)
from stg_site_daily d
join stg_site_daily f on f.source_table = d.source_table and f._row = d.first_row
where d.rn > 1 and d.day is not null;

-- Flags (bitmask, see clean.dq_rule).
create temp table stg_site_daily_flag on commit drop as
select *,
       (case when e is null or i is null                          then 1   else 0 end)
     | (case when e < 0                                           then 2   else 0 end)
     | (case when i <= 0 and e > 0                                then 4   else 0 end)
     | (case when e > 0 and i > 0 and e / (cap_mwp * i) > 1.0     then 8   else 0 end)
     | (case when a < 0 or a > 100                                then 16  else 0 end)
     | (case when file_kwp is not null and reg_kwp is not null
              and file_kwp <> reg_kwp                             then 128 else 0 end)
       as flags
from stg_site_daily
where rn = 1 and day is not null;

insert into clean.site_daily (site_id, day, capacity_dc_kwp, energy_mwh, irradiation_kwh_m2,
                              ambient_max_c, availability_pct, panel_cleaning, dq_flags,
                              source_table, source_row)
select site_id, day, file_kwp,
       case when flags & (2 | 8) <> 0 then null else e end,
       case when flags & 4 <> 0 then null else i end,
       amb,
       case when flags & 16 <> 0 and (a < 0 or a > 100) then null else a end,
       cleaned, flags, source_table, _row
from stg_site_daily_flag;

-- One issue row per (row, rule).
insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select f.source_table, r.rule, r.severity, f._row, f.site_code, f.day, f.day,
       format('energy=%s MWh, irradiation=%s kWh/m2, availability=%s %%',
              coalesce(f.raw_e, 'empty'), coalesce(f.raw_i, 'empty'),
              coalesce(f.raw_a, 'n/a')),
       r.action
from stg_site_daily_flag f
join clean.dq_rule r on f.flags & r.bit <> 0;

-- Calendar gaps: days missing between each site's first and last date.
insert into clean.dq_issue (source_table, rule, severity, entity, period_start, period_end,
                            detail, action)
select g.source_table, 'missing_day', 'warn', g.site_code, g.d, g.d,
       'no row for this site and date', 'left missing; period totals exclude it'
from (
  select source_table, site_id, site_code,
         generate_series(min(day), max(day), interval '1 day')::date as d
  from stg_site_daily where day is not null
  group by 1, 2, 3
) g
where not exists (select 1 from clean.site_daily c where c.site_id = g.site_id and c.day = g.d);
