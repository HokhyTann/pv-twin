-- clean.event from the free-text maintenance log (expert site).
-- Categories come from simple keyword rules; first match wins.

insert into clean.event (site_id, asset_id, scope, day, category, note, source_row)
select s.site_id,
       a.asset_id,
       btrim(r.asset) as scope,
       clean.try_date(r.date),
       case
         when r.note ~* 'clean'                                     then 'cleaning'
         when r.note ~* 'firmware'                                  then 'firmware'
         when btrim(r.asset) = 'COMMS'
           or r.note ~* 'modem|communication|data logger|scada'     then 'comms'
         when btrim(r.asset) = 'METER' or r.note ~* 'meter'         then 'meter'
         when r.note ~* 'replaced|back online|restored'             then 'repair'
         when r.note ~* 'fault|failed|isolated'                     then 'fault'
         when r.note ~* 'trip'                                      then 'trip'
         else 'other'
       end,
       btrim(r.note),
       r._row
from raw.expert_maintenance_log r
join core.site s on s.source_dataset = 'expert'
left join core.asset a
       on a.site_id = s.site_id
      and a.code = case when btrim(r.asset) = 'METER' then 'MTR-01' else btrim(r.asset) end
where clean.try_date(r.date) is not null;

insert into clean.dq_issue (source_table, rule, severity, source_row, entity, detail, action)
select 'expert_maintenance_log', 'invalid_date', 'error', _row, asset,
       format('date %L could not be parsed', date), 'row dropped'
from raw.expert_maintenance_log where clean.try_date(date) is null;
