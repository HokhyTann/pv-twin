-- Dataset-level observations (severity 'info'). Each is written only when the data
-- shows the evidence, so they disappear if a corrected file is loaded.

-- SCADA time zone: if average power peaks at 03:00-07:00 UTC, the file is in UTC
-- (that is 10:00-14:00 in Cambodia, UTC+7).
insert into clean.dq_issue (source_table, rule, severity, n_rows, detail, action)
select 'expert_scada_15min', 'timestamps_utc', 'info', (select count(*) from clean.inverter_15min),
       format('average power peaks at %s UTC (%s local), so timestamps are UTC',
              to_char(peak, 'HH24:MI'), to_char(peak + interval '7 hours', 'HH24:MI')),
       'stored as timestamptz in UTC; daily totals use the Asia/Phnom_Penh day'
from (
  select (ts at time zone 'UTC')::time as peak
  from clean.inverter_15min
  group by 1 order by avg(ac_power_kw) desc limit 1
) x
where extract(hour from peak) between 3 and 7;

-- Power exactly at rated AC for consecutive intervals is clipping, not a frozen sensor.
insert into clean.dq_issue (source_table, rule, severity, n_rows, detail, action)
select 'expert_scada_15min', 'clipping_at_rated', 'info', count(*),
       format('%s intervals at exactly rated AC power (%s kW)', count(*), max(rated)),
       format('normal inverter behaviour at DC/AC ratio %s; not treated as an error',
              round(avg(dc_ac), 2))
from (
  select c.ac_power_kw,
         (a.attrs ->> 'rated_ac_kw')::numeric as rated,
         (a.attrs ->> 'dc_kwp')::numeric / (a.attrs ->> 'rated_ac_kw')::numeric as dc_ac
  from clean.inverter_15min c join core.asset a using (asset_id)
) x
where ac_power_kw = rated
having count(*) > 0;

-- Site ambient temperature differs between inverters on the same site and day.
insert into clean.dq_issue (source_table, rule, severity, n_rows, detail, action)
select 'high_inverter_daily', 'ambient_not_site_level', 'info', count(*),
       format('ambient_max_c differs between inverters of the same site-day on %s of %s '
              'site-days (mean range %s C)', count(*) filter (where rng > 0), count(*),
              round(avg(rng), 2)),
       'kept per inverter; use the site-day median when a single site value is needed'
from (
  select a.site_id, d.day, max(d.ambient_max_c) - min(d.ambient_max_c) as rng
  from clean.inverter_daily d join core.asset a using (asset_id)
  group by 1, 2
) x
having avg(rng) > 0.5;

-- ticket_flag is written after repairs, so it leaks the label.
insert into clean.dq_issue (source_table, rule, severity, n_rows, detail, action)
select 'high_inverter_daily', 'label_leakage', 'info', count(*) filter (where ticket_flag),
       format('ticket_flag=1 on %s rows; %s %% of them are positive-label rows '
              '(base rate %s %%)',
              count(*) filter (where ticket_flag),
              round(100.0 * count(*) filter (where ticket_flag and failure_next_7d)
                    / nullif(count(*) filter (where ticket_flag), 0), 1),
              round(100.0 * avg(failure_next_7d::int), 2)),
       'never use ticket_flag as a model feature'
from clean.inverter_daily;
