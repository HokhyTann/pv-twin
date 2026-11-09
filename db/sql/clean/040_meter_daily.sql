-- clean.meter_daily from the expert revenue-meter file. Runs after 030 (needs SCADA).

create temp table stg_meter on commit drop as
select r._row, a.asset_id, a.code,
       clean.try_date(r.date)       as day,
       clean.try_num(r.export_kwh)  as kwh,
       r.export_kwh                 as raw_kwh,
       row_number() over (partition by clean.try_date(r.date) order by r._row) as rn,
       first_value(r._row) over (partition by clean.try_date(r.date) order by r._row) as first_row
from raw.expert_meter_daily r
join core.site s on s.source_dataset = 'expert'
join core.asset a on a.site_id = s.site_id and a.code = 'MTR-01';

insert into clean.dq_issue (source_table, rule, severity, source_row, entity, detail, action)
select 'expert_meter_daily', 'invalid_date', 'error', _row, code,
       'date could not be parsed', 'row dropped'
from stg_meter where day is null;

insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select 'expert_meter_daily', 'duplicate_row', 'warn', _row, code, day, day,
       format('same date as line %s', first_row), format('dropped (line %s kept)', first_row)
from stg_meter where rn > 1 and day is not null;

-- SCADA energy per local day, to tell a real zero (site off) from a missing reading.
create temp table stg_meter_flag on commit drop as
with scada as (
  select (ts at time zone 'Asia/Phnom_Penh')::date as day, sum(ac_power_kw) * 0.25 as kwh
  from clean.inverter_15min group by 1
),
typical as (select percentile_cont(0.5) within group (order by kwh) as med from scada)
select m.*, sc.kwh as scada_kwh,
       (case when m.kwh is null                                       then 1  else 0 end)
     | (case when m.kwh < 0                                           then 2  else 0 end)
     | (case when m.kwh = 0 and sc.kwh > 0.10 * (select med from typical)
                                                                      then 64 else 0 end)
       as flags
from stg_meter m
left join scada sc using (day)
where m.rn = 1 and m.day is not null;

insert into clean.meter_daily (asset_id, day, export_kwh, dq_flags, source_row)
select asset_id, day, case when flags & (2 | 64) <> 0 then null else kwh end, flags, _row
from stg_meter_flag;

insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select 'expert_meter_daily', r.rule, r.severity, f._row, f.code, f.day, f.day,
       format('meter=%s kWh, SCADA=%s kWh', coalesce(f.raw_kwh, 'empty'), round(f.scada_kwh)),
       r.action
from stg_meter_flag f
join clean.dq_rule r on f.flags & r.bit <> 0;

insert into clean.dq_issue (source_table, rule, severity, entity, period_start, period_end,
                            detail, action)
select 'expert_meter_daily', 'missing_day', 'warn', 'MTR-01', g.d, g.d,
       'no meter reading for this date', 'left missing'
from (select generate_series(min(day), max(day), interval '1 day')::date d
      from clean.meter_daily) g
where not exists (select 1 from clean.meter_daily c where c.day = g.d);
