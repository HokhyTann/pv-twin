-- clean.inverter_daily from the high (fleet) dataset.

create temp table stg_inv_daily on commit drop as
select r._row, a.asset_id, s.site_code || '/' || a.code as entity,
       clean.try_date(r.date)               as day,
       btrim(r.online) = '1'                as online,
       clean.try_num(r.energy_kwh)          as energy,
       clean.try_num(r.efficiency_pct)      as eff,
       clean.try_num(r.igbt_max_temp_c)     as igbt,
       clean.try_num(r.fan_speed_rpm)       as fan,
       clean.try_num(r.alarm_count)::int    as alarms,
       clean.try_num(r.ambient_max_c)       as amb,
       btrim(r.ticket_flag) = '1'           as ticket,
       btrim(r.failure_next_7d) = '1'       as label,
       row_number() over (partition by a.asset_id, clean.try_date(r.date) order by r._row) as rn,
       first_value(r._row) over (partition by a.asset_id, clean.try_date(r.date)
                                 order by r._row) as first_row
from raw.high_inverter_daily r
join core.site s on s.source_dataset = 'high' and s.source_code = btrim(r.site)
join core.asset a on a.site_id = s.site_id and a.code = btrim(r.inverter_id);

insert into clean.dq_issue (source_table, rule, severity, source_row, entity, detail, action)
select 'high_inverter_daily', 'invalid_date', 'error', _row, entity,
       'date could not be parsed', 'row dropped'
from stg_inv_daily where day is null;

insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select 'high_inverter_daily', 'duplicate_row', 'warn', _row, entity, day, day,
       format('same inverter and date as line %s', first_row),
       format('dropped (line %s kept)', first_row)
from stg_inv_daily where rn > 1 and day is not null;

-- Sensor values are expected to be empty when the inverter is offline (online = 0).
create temp table stg_inv_daily_flag on commit drop as
select *,
       (case when energy is null
               or (online and (eff is null or igbt is null or fan is null or alarms is null))
                                                                      then 1  else 0 end)
     | (case when energy < 0                                          then 2  else 0 end)
     | (case when eff <= 0 or eff > 100 or igbt not between -20 and 150
               or fan < 0 or alarms < 0 or (not online and energy > 0)
                                                                      then 16 else 0 end)
       as flags
from stg_inv_daily
where rn = 1 and day is not null;

insert into clean.inverter_daily (asset_id, day, online, energy_kwh, efficiency_pct,
                                  igbt_max_temp_c, fan_speed_rpm, alarm_count, ambient_max_c,
                                  ticket_flag, failure_next_7d, dq_flags, source_row)
select asset_id, day, online,
       case when flags & 2 <> 0 then null else energy end,
       eff, igbt, fan, alarms, amb, ticket, label, flags, _row
from stg_inv_daily_flag;

insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select 'high_inverter_daily', r.rule, r.severity, f._row, f.entity, f.day, f.day,
       format('online=%s energy=%s kWh eff=%s %% igbt=%s C fan=%s rpm alarms=%s',
              f.online::int, f.energy, f.eff, f.igbt, f.fan, f.alarms),
       r.action
from stg_inv_daily_flag f
join clean.dq_rule r on f.flags & r.bit <> 0;

-- Label check: failure_next_7d should be 1 exactly when an outage starts 1-7 days later.
with starts as (
  select asset_id, day
  from (select asset_id, day, online,
               lag(online) over (partition by asset_id order by day) as prev
        from clean.inverter_daily) x
  where not online and prev
),
expected as (
  select d.asset_id, d.day, d.failure_next_7d as label, d.source_row,
         exists (select 1 from starts s
                 where s.asset_id = d.asset_id
                   and s.day between d.day + 1 and d.day + 7) as should_be
  from clean.inverter_daily d
  -- the last 7 days cannot be verified: their window runs past the end of the data
  where d.day <= (select max(day) - 7 from clean.inverter_daily)
)
insert into clean.dq_issue (source_table, rule, severity, source_row, entity,
                            period_start, period_end, detail, action)
select 'high_inverter_daily', 'label_inconsistent', 'warn', e.source_row,
       s.site_code || '/' || a.code, e.day, e.day,
       format('failure_next_7d=%s but an outage %s within the next 1-7 days',
              e.label::int, case when e.should_be then 'does start' else 'does not start' end),
       'label kept as given; review before training'
from expected e
join core.asset a using (asset_id)
join core.site s using (site_id)
where e.label is distinct from e.should_be;
