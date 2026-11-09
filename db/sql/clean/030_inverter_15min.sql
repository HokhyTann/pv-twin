-- clean.inverter_15min from the expert SCADA export.
-- Timestamps in the file are UTC (production peaks around 05:00 = 12:00 local);
-- see 090_dataset_notes.sql for the evidence check. Local day = Asia/Phnom_Penh.

create temp table stg_scada on commit drop as
select r._row, btrim(r.inverter_id) as code, a.asset_id,
       (a.attrs ->> 'rated_ac_kw')::numeric as rated_kw,
       clean.try_ts(r.timestamp, 'UTC')    as ts,
       clean.try_num(r.ac_power_kw)        as p,
       row_number() over (partition by btrim(r.inverter_id), clean.try_ts(r.timestamp, 'UTC')
                          order by r._row) as rn
from raw.expert_scada_15min r
left join core.asset a
       on a.site_id = (select site_id from core.site where source_dataset = 'expert')
      and a.code = btrim(r.inverter_id) and a.asset_type = 'inverter';

-- Inverters not in the asset register cannot be attributed: log once per code.
insert into clean.dq_issue (source_table, rule, severity, entity, n_rows, detail, action)
select 'expert_scada_15min', 'unknown_asset', 'error', code, count(*),
       'inverter_id not found in the asset register', 'rows dropped'
from stg_scada where asset_id is null group by code;

insert into clean.dq_issue (source_table, rule, severity, entity, n_rows, detail, action)
select 'expert_scada_15min', 'invalid_timestamp', 'error', code, count(*),
       'timestamp could not be parsed', 'rows dropped'
from stg_scada where asset_id is not null and ts is null group by code;

insert into clean.dq_issue (source_table, rule, severity, entity, n_rows, detail, action)
select 'expert_scada_15min', 'duplicate_row', 'warn', code, count(*),
       'repeated (inverter, timestamp)', 'dropped (first line kept)'
from stg_scada where rn > 1 and asset_id is not null and ts is not null group by code;

-- Scaling check, done per local day: an inverter whose daily energy is >15 % above the
-- median of its peers for 3+ consecutive days is reading a multiple of reality.
create temp table stg_scaling_days on commit drop as
with daily as (
  select asset_id, code, (ts at time zone 'Asia/Phnom_Penh')::date as d, sum(p) * 0.25 as kwh
  from stg_scada where rn = 1 and asset_id is not null and ts is not null
  group by 1, 2, 3
),
ratio as (
  select d.*, d.kwh / nullif(m.med, 0) as r
  from daily d
  join (select d, percentile_cont(0.5) within group (order by kwh) as med
        from daily group by d) m using (d)
),
runs as (
  select *, d - (row_number() over (partition by asset_id order by d))::int as grp
  from ratio where r > 1.15
)
select asset_id, code, grp, min(d) as d0, max(d) as d1, count(*) as n_days,
       avg(r)::numeric as avg_ratio, stddev_samp(r)::numeric as sd_ratio
from runs group by asset_id, code, grp
having count(*) >= 3;

insert into clean.inverter_15min (asset_id, ts, ac_power_kw, dq_flags)
select s.asset_id, s.ts, case when s.p < 0 then null else s.p end,
       (case when s.p is null                              then 1  else 0 end)
     | (case when s.p < 0                                  then 2  else 0 end)
     | (case when s.p > s.rated_kw * 1.02                  then 16 else 0 end)
     | (case when exists (select 1 from stg_scaling_days k
                          where k.asset_id = s.asset_id
                            and (s.ts at time zone 'Asia/Phnom_Penh')::date
                                between k.d0 and k.d1)    then 32 else 0 end)
from stg_scada s
where s.rn = 1 and s.asset_id is not null and s.ts is not null;

-- Interval-level issues are logged per inverter and rule (one line each, with counts),
-- except scaling, which is logged per run with its ratio.
insert into clean.dq_issue (source_table, rule, severity, entity, period_start, period_end,
                            n_rows, detail, action)
select 'expert_scada_15min', r.rule, r.severity, a.code, min(c.ts), max(c.ts), count(*),
       case r.rule
         when 'out_of_range' then format('power above 102 %% of rated AC; max %s kW',
                                         max(c.ac_power_kw))
         else r.description end,
       r.action
from clean.inverter_15min c
join core.asset a using (asset_id)
join clean.dq_rule r on c.dq_flags & r.bit <> 0 and r.rule <> 'scaling_suspect'
group by a.code, r.rule, r.severity, r.description, r.action;

insert into clean.dq_issue (source_table, rule, severity, entity, period_start, period_end,
                            n_rows, detail, action)
select 'expert_scada_15min', 'scaling_suspect', 'warn', k.code,
       k.d0::timestamp at time zone 'Asia/Phnom_Penh',
       (k.d1 + 1)::timestamp at time zone 'Asia/Phnom_Penh',
       k.n_days * 96,
       format('daily energy %s x peer median for %s days (sd %s)',
              round(k.avg_ratio, 3), k.n_days, round(k.sd_ratio, 3)),
       (select action from clean.dq_rule where rule = 'scaling_suspect')
from stg_scaling_days k;

-- Missing 15-minute intervals per inverter (between the file's first and last timestamp).
with bounds as (select min(ts) t0, max(ts) t1 from clean.inverter_15min),
grid as (
  select a.asset_id, a.code, g.ts
  from (select distinct asset_id from clean.inverter_15min) i
  join core.asset a using (asset_id)
  cross join bounds b
  cross join lateral generate_series(b.t0, b.t1, interval '15 min') g(ts)
)
insert into clean.dq_issue (source_table, rule, severity, entity, period_start, period_end,
                            n_rows, detail, action)
select 'expert_scada_15min', 'missing_interval', 'warn', code, min(ts), max(ts), count(*),
       'no SCADA record for these 15-minute intervals', 'left missing (not filled)'
from grid g
where not exists (select 1 from clean.inverter_15min c
                  where c.asset_id = g.asset_id and c.ts = g.ts)
group by code;
