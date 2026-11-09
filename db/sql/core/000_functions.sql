-- Safe casts used by the clean layer. Unparseable text returns NULL (and is then
-- flagged as missing_value) instead of failing the whole transform.

create or replace function clean.try_num(v text) returns numeric
language sql immutable as $$
  select case when btrim(v) ~ '^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$' then btrim(v)::numeric end
$$;

create or replace function clean.try_date(v text) returns date
language plpgsql immutable as $$
begin
  return case when btrim(v) ~ '^\d{4}-\d{2}-\d{2}$' then btrim(v)::date end;
exception when others then
  return null;
end
$$;

-- Naive 'YYYY-MM-DD HH:MI[:SS]' text interpreted in the given time zone.
create or replace function clean.try_ts(v text, tz text) returns timestamptz
language plpgsql immutable as $$
begin
  return case when btrim(v) ~ '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$'
              then btrim(v)::timestamp at time zone tz end;
exception when others then
  return null;
end
$$;

-- Human-readable list of rule names for a dq_flags bitmask.
create or replace function clean.dq_rules_of(flags int) returns text[]
language sql stable as $$
  select coalesce(array_agg(rule order by bit), '{}') from clean.dq_rule where flags & bit <> 0
$$;
