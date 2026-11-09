-- The clean layer is rebuilt from raw on every run.
truncate clean.dq_issue restart identity;
truncate clean.site_daily, clean.inverter_daily, clean.meter_daily, clean.event restart identity;
delete from clean.inverter_15min;
