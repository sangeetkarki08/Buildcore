-- BuildCore web 2.29.0: the database layout, for Supabase (PostgreSQL 15 or newer).
--
-- You do not have to run this file. BuildCore creates and upgrades these tables by itself the first
-- time it starts, the same way the desktop app prepares its data file. Run it only if you want the
-- tables in place before the first start: Supabase > SQL Editor > New query > paste this file > Run.
-- Running it on a database that already has BuildCore tables stops with "already exists" and changes nothing.
--
-- Schema "buildcore" holds the company's data (one more schema per extra company, made by the app).
-- Schema "bcfn" holds helper functions that give PostgreSQL the few SQLite functions BuildCore uses.
-- Neither is reachable through Supabase's public API: access is revoked for the anon and authenticated
-- roles below, and BuildCore connects with the database connection string only.

--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: bcfn; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA bcfn;


--
-- Name: SCHEMA bcfn; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA bcfn IS 'bcfn-10';


--
-- Name: buildcore; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA buildcore;


--
-- Name: _apply(text, text[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn._apply(x text, mods text[]) RETURNS timestamp without time zone
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE t timestamp := bcfn._ts(x); m text;
BEGIN
  IF mods IS NOT NULL THEN FOREACH m IN ARRAY mods LOOP t := bcfn._mod(t, m); END LOOP; END IF;
  RETURN t;
END $$;


--
-- Name: _mod(timestamp without time zone, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn._mod(t timestamp without time zone, m text) RETURNS timestamp without time zone
    LANGUAGE plpgsql STABLE
    AS $_$
DECLARE mm text := lower(btrim(m)); n double precision; u text;
BEGIN
  IF t IS NULL THEN RETURN NULL; END IF;
  IF mm = 'localtime' THEN RETURN (t AT TIME ZONE 'utc') AT TIME ZONE coalesce(current_setting('bco.tz', true), 'Asia/Kathmandu'); END IF;
  IF mm = 'utc' THEN RETURN t; END IF;
  IF mm = 'start of month' THEN RETURN date_trunc('month', t); END IF;
  IF mm = 'start of year' THEN RETURN date_trunc('year', t); END IF;
  IF mm = 'start of day' THEN RETURN date_trunc('day', t); END IF;
  IF mm LIKE 'weekday %' THEN
    n := substr(mm, 9)::int;
    RETURN t + ((((n::int - extract(dow FROM t)::int) % 7) + 7) % 7) * interval '1 day';
  END IF;
  n := substring(mm from '^[-+]?[0-9]*\.?[0-9]+')::double precision;
  u := btrim(substring(mm from '[a-z]+$'));
  IF u IN ('day','days') THEN RETURN t + n * interval '1 day'; END IF;
  IF u IN ('month','months') THEN RETURN t + (n::int) * interval '1 month'; END IF;
  IF u IN ('year','years') THEN RETURN t + (n::int) * interval '1 year'; END IF;
  IF u IN ('hour','hours') THEN RETURN t + n * interval '1 hour'; END IF;
  IF u IN ('minute','minutes') THEN RETURN t + n * interval '1 minute'; END IF;
  IF u IN ('second','seconds') THEN RETURN t + n * interval '1 second'; END IF;
  RETURN t;
END $_$;


--
-- Name: _ts(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn._ts(x text) RETURNS timestamp without time zone
    LANGUAGE plpgsql STABLE
    AS $_$
BEGIN
  IF x IS NULL OR btrim(x) = '' THEN RETURN NULL; END IF;
  IF lower(x) = 'now' THEN RETURN (now() AT TIME ZONE 'utc'); END IF;
  IF x ~ '^-?[0-9]+(\.[0-9]+)?$' THEN RETURN timestamp '4714-11-24 12:00:00 BC' + (x::double precision * interval '1 day'); END IF;
  BEGIN RETURN x::timestamp; EXCEPTION WHEN others THEN RETURN NULL; END;
END $_$;


--
-- Name: abs(double precision); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.abs(x double precision) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT abs(x) $$;


--
-- Name: abs(bigint); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.abs(x bigint) RETURNS bigint
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT abs(x) $$;


--
-- Name: abs(numeric); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.abs(x numeric) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT abs(x) $$;


--
-- Name: abs(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.abs(x text) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT abs(bcfn.to_real(x)) $$;


--
-- Name: bool_avg_final(bigint[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.bool_avg_final(s bigint[]) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT CASE WHEN s[2] = 0 THEN NULL ELSE s[1]::double precision / s[2] END $$;


--
-- Name: bool_avg_sfunc(bigint[], boolean); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.bool_avg_sfunc(s bigint[], x boolean) RETURNS bigint[]
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT CASE WHEN x IS NULL THEN s ELSE ARRAY[s[1] + x::int, s[2] + 1] END $$;


--
-- Name: bool_sfunc(bigint, boolean); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.bool_sfunc(s bigint, x boolean) RETURNS bigint
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT CASE WHEN x IS NULL THEN s ELSE COALESCE(s, 0) + x::int END $$;


--
-- Name: date(anyelement, text[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.date(x anyelement, VARIADIC mods text[] DEFAULT NULL::text[]) RETURNS text
    LANGUAGE sql STABLE
    AS $$
  SELECT to_char(bcfn._apply(x::text, mods), 'YYYY-MM-DD') $$;


--
-- Name: date(text, text[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.date(x text, VARIADIC mods text[] DEFAULT NULL::text[]) RETURNS text
    LANGUAGE sql STABLE
    AS $$
  SELECT to_char(bcfn._apply(x, mods), 'YYYY-MM-DD') $$;


--
-- Name: datetime(text, text[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.datetime(x text, VARIADIC mods text[] DEFAULT NULL::text[]) RETURNS text
    LANGUAGE sql STABLE
    AS $$
  SELECT to_char(bcfn._apply(x, mods), 'YYYY-MM-DD HH24:MI:SS') $$;


--
-- Name: instr(text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.instr(x text, y text) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT strpos(x, y) $$;


--
-- Name: json_extract(text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.json_extract(j text, p text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    AS $_$
DECLARE path text[];
BEGIN
  IF j IS NULL OR btrim(j) = '' THEN RETURN NULL; END IF;
  path := string_to_array(regexp_replace(regexp_replace(p, '^\$\.?', ''), '\[(\d+)\]', '.\1', 'g'), '.');
  BEGIN RETURN j::jsonb #>> path; EXCEPTION WHEN others THEN RETURN NULL; END;
END $_$;


--
-- Name: julianday(text, text[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.julianday(x text, VARIADIC mods text[] DEFAULT NULL::text[]) RETURNS double precision
    LANGUAGE sql STABLE
    AS $$
  SELECT extract(epoch FROM bcfn._apply(x, mods) - timestamp '4714-11-24 12:00:00 BC') / 86400.0 $$;


--
-- Name: length(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.length(x anyelement) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT length(x::text) $$;


--
-- Name: length(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.length(x text) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT length(x) $$;


--
-- Name: lower(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.lower(x anyelement) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT lower(x::text) $$;


--
-- Name: lower(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.lower(x text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT lower(x) $$;


--
-- Name: ltrim(text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.ltrim(x text, c text DEFAULT ' '::text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT ltrim(x, c) $$;


--
-- Name: next_id(text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.next_id(tbl text, col text DEFAULT 'id'::text) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE m bigint; k text := 'bco.n' || md5(current_schema() || '.' || tbl); memo text;
        st text := statement_timestamp()::text;
BEGIN
  EXECUTE format('SELECT COALESCE(MAX(%I), 0) + 1 FROM %I.%I', col, current_schema(), tbl) INTO m;
  memo := current_setting(k, true);
  IF memo IS NOT NULL AND memo <> '' AND split_part(memo, '|', 1) = st AND split_part(memo, '|', 2)::bigint >= m THEN
    m := split_part(memo, '|', 2)::bigint + 1;   -- several rows in one statement
  END IF;
  PERFORM set_config(k, st || '|' || m, true);
  RETURN m;
END $$;


--
-- Name: random(); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.random() RETURNS bigint
    LANGUAGE sql
    AS $$
  SELECT (random() * 9223372036854775807)::bigint - 4611686018427387903 $$;


--
-- Name: replace(anyelement, text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.replace(x anyelement, a text, b text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT replace(x::text, a, b) $$;


--
-- Name: replace(text, text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.replace(x text, a text, b text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT replace(x, a, b) $$;


--
-- Name: round(double precision, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.round(x double precision, n integer DEFAULT 0) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT round(x::numeric, n)::double precision $$;


--
-- Name: round(bigint, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.round(x bigint, n integer DEFAULT 0) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT x::double precision $$;


--
-- Name: round(numeric, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.round(x numeric, n integer DEFAULT 0) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT round(x, n)::double precision $$;


--
-- Name: round(text, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.round(x text, n integer DEFAULT 0) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT round(bcfn.to_real(x)::numeric, n)::double precision $$;


--
-- Name: rtrim(text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.rtrim(x text, c text DEFAULT ' '::text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT rtrim(x, c) $$;


--
-- Name: strftime(text, text, text[]); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.strftime(f text, x text, VARIADIC mods text[] DEFAULT NULL::text[]) RETURNS text
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE t timestamp := bcfn._apply(x, mods); r text := f;
BEGIN
  IF t IS NULL THEN RETURN NULL; END IF;
  r := replace(r, '%Y', to_char(t, 'YYYY')); r := replace(r, '%m', to_char(t, 'MM'));
  r := replace(r, '%d', to_char(t, 'DD'));   r := replace(r, '%H', to_char(t, 'HH24'));
  r := replace(r, '%M', to_char(t, 'MI'));   r := replace(r, '%S', to_char(t, 'SS'));
  r := replace(r, '%w', extract(dow FROM t)::int::text); r := replace(r, '%j', to_char(t, 'DDD'));
  r := replace(r, '%W', lpad(to_char(t, 'WW'), 2, '0')); r := replace(r, '%s', extract(epoch FROM t)::bigint::text);
  r := replace(r, '%%', '%');
  RETURN r;
END $$;


--
-- Name: substr(anyelement, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.substr(x anyelement, s integer) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT bcfn.substr(x::text, s) $$;


--
-- Name: substr(text, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.substr(x text, s integer) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT CASE WHEN s > 0 THEN substr(x, s) WHEN s = 0 THEN substr(x, 1) ELSE right(x, -s) END $$;


--
-- Name: substr(anyelement, integer, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.substr(x anyelement, s integer, n integer) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT bcfn.substr(x::text, s, n) $$;


--
-- Name: substr(text, integer, integer); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.substr(x text, s integer, n integer) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT CASE WHEN s > 0 THEN substr(x, s, n)
              WHEN s = 0 THEN substr(x, 1, greatest(n - 1, 0))
              ELSE substr(x, length(x) + s + 1, n) END $$;


--
-- Name: to_int(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.to_int(x anyelement) RETURNS bigint
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT trunc(bcfn.to_real(x::text))::bigint $$;


--
-- Name: to_int(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.to_int(x text) RETURNS bigint
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT trunc(bcfn.to_real(x))::bigint $$;


--
-- Name: to_num(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.to_num(x anyelement) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT bcfn.to_real(x::text)::numeric $$;


--
-- Name: to_num(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.to_num(x text) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT bcfn.to_real(x)::numeric $$;


--
-- Name: to_real(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.to_real(x anyelement) RETURNS double precision
    LANGUAGE plpgsql IMMUTABLE
    AS $$
BEGIN
  IF x IS NULL THEN RETURN NULL; END IF;
  BEGIN RETURN x::text::double precision;
  EXCEPTION WHEN others THEN
    RETURN COALESCE(NULLIF(substring(btrim(x::text) from '^[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?'), ''), '0')::double precision;
  END;
END $$;


--
-- Name: to_real(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.to_real(x text) RETURNS double precision
    LANGUAGE plpgsql IMMUTABLE
    AS $$
BEGIN
  IF x IS NULL THEN RETURN NULL; END IF;
  BEGIN RETURN x::double precision;
  EXCEPTION WHEN others THEN
    RETURN COALESCE(NULLIF(substring(btrim(x) from '^[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?'), ''), '0')::double precision;
  END;
END $$;


--
-- Name: total_sfunc(double precision, double precision); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.total_sfunc(s double precision, x double precision) RETURNS double precision
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT s + COALESCE(x, 0) $$;


--
-- Name: trim(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn."trim"(x anyelement) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT btrim(x::text) $$;


--
-- Name: trim(text, text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn."trim"(x text, c text DEFAULT ' '::text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT btrim(x, c) $$;


--
-- Name: truthy(boolean); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.truthy(x boolean) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT x $$;


--
-- Name: truthy(double precision); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.truthy(x double precision) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT x <> 0 $$;


--
-- Name: truthy(bigint); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.truthy(x bigint) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT x <> 0 $$;


--
-- Name: truthy(numeric); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.truthy(x numeric) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT x <> 0 $$;


--
-- Name: truthy(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.truthy(x text) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT bcfn.to_real(x) <> 0 $$;


--
-- Name: typeof(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.typeof(x anyelement) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $_$
  SELECT CASE WHEN x IS NULL THEN 'null' WHEN pg_typeof(x)::text IN ('integer','bigint','smallint') THEN 'integer'
              WHEN pg_typeof(x)::text = 'numeric' THEN CASE WHEN x::text ~ '^-?[0-9]+$' THEN 'integer' ELSE 'real' END
              WHEN pg_typeof(x)::text IN ('double precision','real') THEN 'real'
              WHEN pg_typeof(x)::text = 'bytea' THEN 'blob' ELSE 'text' END $_$;


--
-- Name: upper(anyelement); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.upper(x anyelement) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT upper(x::text) $$;


--
-- Name: upper(text); Type: FUNCTION; Schema: bcfn; Owner: -
--

CREATE FUNCTION bcfn.upper(x text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$ SELECT upper(x) $$;


--
-- Name: trg_bco_vline_no_delete(); Type: FUNCTION; Schema: buildcore; Owner: -
--

CREATE FUNCTION buildcore.trg_bco_vline_no_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF (SELECT status FROM vouchers WHERE id=OLD.voucher_id) IN ('posted','reversed') THEN RAISE EXCEPTION 'Lines of a posted voucher cannot be deleted. Reverse the voucher instead.'; END IF; RETURN OLD; END $$;


--
-- Name: trg_bco_vline_no_edit(); Type: FUNCTION; Schema: buildcore; Owner: -
--

CREATE FUNCTION buildcore.trg_bco_vline_no_edit() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF (SELECT status FROM vouchers WHERE id=OLD.voucher_id) IN ('posted','reversed') THEN RAISE EXCEPTION 'Amounts and accounts of a posted voucher cannot be changed. Reverse it instead.'; END IF; RETURN NEW; END $$;


--
-- Name: trg_bco_voucher_no_delete(); Type: FUNCTION; Schema: buildcore; Owner: -
--

CREATE FUNCTION buildcore.trg_bco_voucher_no_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF OLD.status IN ('posted','reversed') THEN RAISE EXCEPTION 'Posted vouchers cannot be deleted. Reverse them instead (NFRS: vouchers are permanent).'; END IF; RETURN OLD; END $$;


--
-- Name: trg_bco_voucher_no_edit(); Type: FUNCTION; Schema: buildcore; Owner: -
--

CREATE FUNCTION buildcore.trg_bco_voucher_no_edit() RETURNS trigger
    LANGUAGE plpgsql
    AS $$ BEGIN IF OLD.status IN ('posted','reversed') AND (NEW.date IS DISTINCT FROM OLD.date OR NEW.total IS DISTINCT FROM OLD.total OR NEW.no IS DISTINCT FROM OLD.no OR NEW.type IS DISTINCT FROM OLD.type OR NEW.project_id IS DISTINCT FROM OLD.project_id OR NEW.party_id IS DISTINCT FROM OLD.party_id OR NEW.source IS DISTINCT FROM OLD.source OR NEW.source_id IS DISTINCT FROM OLD.source_id OR (OLD.status='reversed' AND NEW.status<>'reversed') OR (OLD.status='posted' AND NEW.status NOT IN ('posted','reversed'))) THEN RAISE EXCEPTION 'A posted voucher cannot be changed. Post a reversal and a new voucher instead.'; END IF; RETURN NEW; END $$;


--
-- Name: avg(boolean); Type: AGGREGATE; Schema: bcfn; Owner: -
--

CREATE AGGREGATE bcfn.avg(boolean) (
    SFUNC = bcfn.bool_avg_sfunc,
    STYPE = bigint[],
    INITCOND = '{0,0}',
    FINALFUNC = bcfn.bool_avg_final
);


--
-- Name: sum(boolean); Type: AGGREGATE; Schema: bcfn; Owner: -
--

CREATE AGGREGATE bcfn.sum(boolean) (
    SFUNC = bcfn.bool_sfunc,
    STYPE = bigint
);


--
-- Name: total(boolean); Type: AGGREGATE; Schema: bcfn; Owner: -
--

CREATE AGGREGATE bcfn.total(boolean) (
    SFUNC = bcfn.bool_sfunc,
    STYPE = bigint,
    INITCOND = '0'
);


--
-- Name: total(double precision); Type: AGGREGATE; Schema: bcfn; Owner: -
--

CREATE AGGREGATE bcfn.total(double precision) (
    SFUNC = bcfn.total_sfunc,
    STYPE = double precision,
    INITCOND = '0'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account_groups; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.account_groups (
    id bigint DEFAULT bcfn.next_id('account_groups'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    type text,
    parent_id numeric
);


--
-- Name: accounts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.accounts (
    id bigint DEFAULT bcfn.next_id('accounts'::text, 'id'::text) NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    type text NOT NULL,
    group_id numeric,
    role text,
    opening_balance double precision DEFAULT 0,
    bank_name text,
    bank_acno text,
    active numeric DEFAULT 1
);


--
-- Name: act_links; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.act_links (
    id bigint DEFAULT bcfn.next_id('act_links'::text, 'id'::text) NOT NULL,
    project_id numeric,
    pred_id numeric,
    succ_id numeric,
    type text DEFAULT 'FS'::text,
    lag double precision DEFAULT 0
);


--
-- Name: act_resources; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.act_resources (
    id bigint DEFAULT bcfn.next_id('act_resources'::text, 'id'::text) NOT NULL,
    project_id numeric,
    activity_id numeric,
    kind text,
    ref text,
    name text,
    unit text,
    qty_total double precision DEFAULT 0,
    material_id numeric,
    trade_id numeric,
    category text,
    source text DEFAULT 'manual'::text,
    remarks text
);


--
-- Name: activities; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.activities (
    id bigint DEFAULT bcfn.next_id('activities'::text, 'id'::text) NOT NULL,
    project_id numeric NOT NULL,
    wbs_id numeric,
    code text,
    name text,
    boq_item_id numeric,
    location text,
    unit text,
    planned_qty double precision DEFAULT 0,
    planned_start text,
    planned_finish text,
    baseline_start text,
    baseline_finish text,
    actual_start text,
    actual_finish text,
    weight double precision DEFAULT 0,
    responsible text,
    predecessors text,
    is_milestone numeric DEFAULT 0,
    critical numeric DEFAULT 0,
    std_labour_prod double precision DEFAULT 0,
    std_equip_prod double precision DEFAULT 0,
    test_required text,
    delay_reason text,
    actual_qty double precision DEFAULT 0,
    duration double precision,
    calendar_id numeric,
    work_type text,
    weather_sensitive numeric,
    constraint_type text,
    constraint_date text,
    es text,
    ef text,
    ls text,
    lf text,
    tf double precision,
    ff double precision,
    indep_float double precision,
    interf_float double precision,
    near_critical numeric,
    remaining_dur double precision,
    remaining_override double precision,
    pct_complete double precision,
    driver_id numeric,
    foreman text,
    weather_days double precision,
    crash_dur double precision,
    crash_cost double precision,
    normal_cost double precision,
    dur_opt double precision,
    dur_likely double precision,
    dur_pess double precision,
    chainage_from double precision,
    chainage_to double precision,
    linear_order numeric,
    norm_code text,
    act_start_override text,
    act_finish_override text
);


--
-- Name: activity; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.activity (
    id bigint DEFAULT bcfn.next_id('activity'::text, 'id'::text) NOT NULL,
    ts text,
    user_id numeric,
    user_name text,
    location text,
    project_id numeric,
    kind text,
    title text,
    detail text,
    link text,
    amount double precision
);


--
-- Name: ai_config; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ai_config (
    key text NOT NULL,
    value text
);


--
-- Name: ai_doc_pages; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ai_doc_pages (
    doc_id numeric NOT NULL,
    page numeric NOT NULL,
    text text
);


--
-- Name: ai_docs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ai_docs (
    id bigint DEFAULT bcfn.next_id('ai_docs'::text, 'id'::text) NOT NULL,
    file_id numeric,
    contract_id numeric,
    project_id numeric,
    title text,
    doc_type text,
    pages numeric DEFAULT 0,
    chars numeric DEFAULT 0,
    scanned numeric DEFAULT 0,
    status text DEFAULT 'new'::text,
    error text,
    indexed_at text,
    abstract_at text,
    created_by numeric,
    created text
);


--
-- Name: ai_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ai_items (
    id bigint DEFAULT bcfn.next_id('ai_items'::text, 'id'::text) NOT NULL,
    doc_id numeric,
    contract_id numeric,
    category text,
    title text,
    detail text,
    value text,
    due_date text,
    repeat text,
    clause text,
    page numeric,
    precondition_for text,
    status text DEFAULT 'proposed'::text,
    citem_id numeric,
    source text DEFAULT 'ai'::text,
    edited_by numeric,
    edited_at text,
    created text
);


--
-- Name: ai_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ai_log (
    id bigint DEFAULT bcfn.next_id('ai_log'::text, 'id'::text) NOT NULL,
    ts text,
    user_id numeric,
    kind text,
    provider text,
    model text,
    in_tokens numeric DEFAULT 0,
    out_tokens numeric DEFAULT 0,
    ok numeric DEFAULT 1,
    note text
);


--
-- Name: allocations; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.allocations (
    id bigint DEFAULT bcfn.next_id('allocations'::text, 'id'::text) NOT NULL,
    payment_id numeric,
    invoice_id numeric,
    amount double precision,
    date text,
    voucher_id numeric,
    active numeric DEFAULT 1
);


--
-- Name: asset_acq; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.asset_acq (
    id bigint DEFAULT bcfn.next_id('asset_acq'::text, 'id'::text) NOT NULL,
    case_id numeric,
    equipment_id numeric,
    step text,
    date text,
    ref text,
    done numeric DEFAULT 0,
    supplier text,
    vetted numeric DEFAULT 0,
    notes text,
    user_id numeric
);


--
-- Name: asset_cases; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.asset_cases (
    id bigint DEFAULT bcfn.next_id('asset_cases'::text, 'id'::text) NOT NULL,
    no text,
    date text,
    title text,
    category text,
    project_id numeric,
    need text,
    hours_year double precision,
    years numeric DEFAULT 5,
    marr double precision DEFAULT 12,
    inputs text,
    result text,
    chosen text,
    risk_likelihood numeric,
    risk_consequence numeric,
    risk_note text,
    savings_year double precision,
    status text DEFAULT 'draft'::text,
    decided_by numeric,
    decided_on text,
    equipment_id numeric,
    remarks text,
    created_by numeric
);


--
-- Name: asset_disposals; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.asset_disposals (
    id bigint DEFAULT bcfn.next_id('asset_disposals'::text, 'id'::text) NOT NULL,
    no text,
    equipment_id numeric,
    asset_id numeric,
    trigger text,
    assessment text,
    assessed_by text,
    application text,
    evaluation_value double precision,
    process text,
    status text DEFAULT 'proposed'::text,
    approved_by numeric,
    approved_on text,
    method text,
    proceeds double precision,
    completed_on text,
    voucher_id numeric,
    remarks text,
    created_by numeric,
    date text
);


--
-- Name: asset_moves; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.asset_moves (
    id bigint DEFAULT bcfn.next_id('asset_moves'::text, 'id'::text) NOT NULL,
    asset_id numeric,
    date text,
    kind text,
    from_location text,
    to_location text,
    from_project numeric,
    to_project numeric,
    custodian text,
    amount double precision DEFAULT 0,
    remarks text,
    voucher_id numeric,
    user_id numeric,
    ts text
);


--
-- Name: assets; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.assets (
    id bigint DEFAULT bcfn.next_id('assets'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    category text,
    class text DEFAULT 'furniture'::text,
    project_id numeric,
    location text,
    custodian text,
    custodian_staff_id numeric,
    supplier_id numeric,
    invoice_no text,
    purchase_date text,
    purchase_value double precision DEFAULT 0,
    residual_value double precision DEFAULT 0,
    life_months numeric DEFAULT 60,
    dep_method text DEFAULT 'slm'::text,
    wdv_rate double precision DEFAULT 0,
    accumulated_dep double precision DEFAULT 0,
    book_value double precision DEFAULT 0,
    serial text,
    warranty_expiry text,
    insurance_policy text,
    insurance_expiry text,
    condition text DEFAULT 'good'::text,
    status text DEFAULT 'in_use'::text,
    disposal_date text,
    disposal_value double precision DEFAULT 0,
    remarks text,
    last_verified text,
    active numeric DEFAULT 1
);


--
-- Name: audit; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.audit (
    id bigint DEFAULT bcfn.next_id('audit'::text, 'id'::text) NOT NULL,
    ts text,
    user_id numeric,
    action text,
    entity text,
    entity_id numeric,
    detail text
);


--
-- Name: bid_prices; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.bid_prices (
    id bigint DEFAULT bcfn.next_id('bid_prices'::text, 'id'::text) NOT NULL,
    bid_id numeric,
    bidder text,
    price double precision,
    is_us numeric DEFAULT 0,
    responsive numeric DEFAULT 1,
    remarks text
);


--
-- Name: bids; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.bids (
    id bigint DEFAULT bcfn.next_id('bids'::text, 'id'::text) NOT NULL,
    no text,
    date text,
    client text,
    title text,
    work_type text,
    location text,
    ee double precision,
    our_cost double precision,
    our_bid double precision,
    markup_pct double precision,
    status text DEFAULT 'preparing'::text,
    winner text,
    winning_bid double precision,
    project_id numeric,
    bid_security double precision,
    submission_date text,
    remarks text,
    created_by numeric
);


--
-- Name: boq_components; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.boq_components (
    id bigint DEFAULT bcfn.next_id('boq_components'::text, 'id'::text) NOT NULL,
    project_id numeric,
    code text,
    name text,
    kind text,
    wbs_id numeric,
    sort numeric DEFAULT 0,
    remarks text,
    active numeric DEFAULT 1
);


--
-- Name: boq_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.boq_items (
    id bigint DEFAULT bcfn.next_id('boq_items'::text, 'id'::text) NOT NULL,
    project_id numeric NOT NULL,
    code text,
    description text,
    unit text,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    executed_qty double precision DEFAULT 0,
    component_id numeric,
    wbs_id numeric,
    location text,
    revised_qty double precision,
    revised_rate double precision
);


--
-- Name: budgets; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.budgets (
    id bigint DEFAULT bcfn.next_id('budgets'::text, 'id'::text) NOT NULL,
    project_id numeric,
    account_id numeric,
    boq_item_id numeric,
    amount double precision DEFAULT 0,
    remarks text
);


--
-- Name: ca_clauses; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ca_clauses (
    id bigint DEFAULT bcfn.next_id('ca_clauses'::text, 'id'::text) NOT NULL,
    project_id numeric,
    form text,
    clause text,
    title text,
    party text,
    trigger text,
    days numeric,
    follow_title text,
    follow_days numeric,
    consequence text,
    system numeric DEFAULT 0,
    active numeric DEFAULT 1,
    ts text
);


--
-- Name: ca_letters; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ca_letters (
    id bigint DEFAULT bcfn.next_id('ca_letters'::text, 'id'::text) NOT NULL,
    project_id numeric,
    contract_id numeric,
    direction text,
    our_no text,
    their_ref text,
    date text,
    received_on text,
    party_id numeric,
    from_name text,
    to_name text,
    subject text,
    category text,
    clause text,
    summary text,
    body text,
    reply_needed numeric DEFAULT 0,
    reply_by text,
    in_reply_to numeric,
    replied_by numeric,
    status text DEFAULT 'open'::text,
    priority text DEFAULT 'normal'::text,
    assigned_to numeric,
    cc text,
    list_id numeric,
    event_id numeric,
    variation_id numeric,
    timebar_id numeric,
    created_by numeric,
    ts text,
    closed_on text
);


--
-- Name: ca_securities; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ca_securities (
    id bigint DEFAULT bcfn.next_id('ca_securities'::text, 'id'::text) NOT NULL,
    project_id numeric,
    contract_id numeric,
    kind text,
    number text,
    issuer text,
    beneficiary text,
    party_id numeric,
    amount double precision,
    currency text DEFAULT 'NPR'::text,
    issue_date text,
    expiry_date text,
    claim_until text,
    status text DEFAULT 'active'::text,
    released_on text,
    history text,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: ca_timebars; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ca_timebars (
    id bigint DEFAULT bcfn.next_id('ca_timebars'::text, 'id'::text) NOT NULL,
    project_id numeric,
    clause_id numeric,
    clause text,
    title text,
    party text,
    trigger_date text,
    due_date text,
    status text DEFAULT 'running'::text,
    done_date text,
    letter_id numeric,
    event_id numeric,
    parent_id numeric,
    notes text,
    created_by numeric,
    ts text
);


--
-- Name: cfw_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cfw_items (
    id bigint DEFAULT bcfn.next_id('cfw_items'::text, 'id'::text) NOT NULL,
    date text,
    kind text,
    amount double precision DEFAULT 0,
    label text,
    category text,
    project_id numeric,
    confidence text DEFAULT 'likely'::text,
    note text,
    active numeric DEFAULT 1,
    created_by numeric,
    ts text
);


--
-- Name: cfw_restricted; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cfw_restricted (
    id bigint DEFAULT bcfn.next_id('cfw_restricted'::text, 'id'::text) NOT NULL,
    name text,
    amount double precision DEFAULT 0,
    account_id numeric,
    from_date text,
    until_date text,
    note text,
    active numeric DEFAULT 1,
    created_by numeric,
    ts text
);


--
-- Name: cfw_snapshots; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cfw_snapshots (
    id bigint DEFAULT bcfn.next_id('cfw_snapshots'::text, 'id'::text) NOT NULL,
    label text,
    week0 text,
    opening double precision,
    scenario text,
    data text,
    user_id numeric,
    user_name text,
    ts text
);


--
-- Name: check_lists; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.check_lists (
    id bigint DEFAULT bcfn.next_id('check_lists'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    category text,
    items text,
    active numeric DEFAULT 1
);


--
-- Name: cl_alloc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_alloc (
    line_id numeric NOT NULL,
    cost_code_id numeric NOT NULL,
    share double precision DEFAULT 1,
    ctype text,
    basis text DEFAULT 'normal'::text,
    how text DEFAULT 'auto'::text,
    user_id numeric,
    ts text
);


--
-- Name: cl_budget_changes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_budget_changes (
    id bigint DEFAULT bcfn.next_id('cl_budget_changes'::text, 'id'::text) NOT NULL,
    project_id numeric,
    kind text,
    cost_code_id numeric,
    variation_id numeric,
    before text,
    after text,
    reason text,
    status text DEFAULT 'proposed'::text,
    proposed_by numeric,
    pm_by numeric,
    pm_at text,
    approved_by numeric,
    approved_at text,
    ts text
);


--
-- Name: cl_budget_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_budget_lines (
    id bigint DEFAULT bcfn.next_id('cl_budget_lines'::text, 'id'::text) NOT NULL,
    version_id numeric,
    cost_code_id numeric,
    qty double precision DEFAULT 0,
    unit_labour double precision DEFAULT 0,
    unit_material double precision DEFAULT 0,
    unit_equip_own double precision DEFAULT 0,
    unit_equip_rent double precision DEFAULT 0,
    unit_subcon double precision DEFAULT 0,
    unit_other double precision DEFAULT 0,
    amount double precision,
    way_of_working text,
    source text,
    placeholder numeric DEFAULT 0,
    note text
);


--
-- Name: cl_budget_versions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_budget_versions (
    id bigint DEFAULT bcfn.next_id('cl_budget_versions'::text, 'id'::text) NOT NULL,
    project_id numeric,
    kind text,
    version_no numeric,
    status text DEFAULT 'draft'::text,
    reason text,
    source text,
    close_id numeric,
    created_by numeric,
    submitted_by numeric,
    submitted_at text,
    approved_by numeric,
    approved_at text,
    ts text
);


--
-- Name: cl_close_accruals; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_close_accruals (
    id bigint DEFAULT bcfn.next_id('cl_close_accruals'::text, 'id'::text) NOT NULL,
    close_id numeric,
    kind text,
    source_type text,
    source_id numeric,
    cost_code_id numeric,
    amount double precision DEFAULT 0,
    voucher_id numeric,
    reversal_id numeric,
    detail text
);


--
-- Name: cl_close_checks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_close_checks (
    close_id numeric NOT NULL,
    check_no numeric NOT NULL,
    result text,
    detail text,
    override_by numeric,
    override_reason text,
    ts text
);


--
-- Name: cl_close_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_close_lines (
    close_id numeric NOT NULL,
    cost_code_id numeric NOT NULL,
    qty_done double precision,
    value_earned double precision,
    cost_posted double precision,
    cost_waiting double precision,
    cost_accrued double precision,
    cost_l double precision,
    cost_m double precision,
    cost_e double precision,
    cost_s double precision,
    cost_o double precision,
    budget_cost_done double precision,
    cost_to_complete double precision,
    eac double precision,
    forecast_value double precision,
    wastage_value double precision,
    flags text,
    data text
);


--
-- Name: cl_close_qty; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_close_qty (
    close_id numeric NOT NULL,
    boq_item_id numeric NOT NULL,
    qty_done double precision DEFAULT 0,
    measured double precision,
    source text,
    note text
);


--
-- Name: cl_close_reopen_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_close_reopen_log (
    id bigint DEFAULT bcfn.next_id('cl_close_reopen_log'::text, 'id'::text) NOT NULL,
    close_id numeric,
    reopened_by numeric,
    reason text,
    at text
);


--
-- Name: cl_close_scqty; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_close_scqty (
    close_id numeric NOT NULL,
    order_item_id numeric NOT NULL,
    qty_done double precision DEFAULT 0,
    note text
);


--
-- Name: cl_closes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_closes (
    id bigint DEFAULT bcfn.next_id('cl_closes'::text, 'id'::text) NOT NULL,
    project_id numeric,
    period text,
    from_date text,
    cutoff_date text,
    status text DEFAULT 'open'::text,
    signed_qs numeric,
    signed_qs_at text,
    signed_accounts numeric,
    signed_accounts_at text,
    signed_pm numeric,
    signed_pm_at text,
    approved_by numeric,
    locked_at text,
    qty_confirmed_by numeric,
    qty_confirmed_at text,
    accruals_at text,
    checks_at text,
    summary text,
    notes text,
    created_by numeric,
    ts text
);


--
-- Name: cl_codes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_codes (
    id bigint DEFAULT bcfn.next_id('cl_codes'::text, 'id'::text) NOT NULL,
    project_id numeric,
    code text,
    kind text,
    boq_item_id numeric,
    name text,
    spread_rule text,
    delay_resp text,
    active numeric DEFAULT 1,
    sort numeric DEFAULT 0,
    ts text
);


--
-- Name: cl_doc_codes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_doc_codes (
    doc text NOT NULL,
    line_id numeric NOT NULL,
    cost_code_id numeric,
    delay_id numeric,
    how text DEFAULT 'manual'::text,
    user_id numeric,
    ts text
);


--
-- Name: cl_eq_months; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_eq_months (
    equipment_id numeric NOT NULL,
    period text NOT NULL,
    available_hrs double precision,
    working_hrs double precision,
    idle_employer double precision,
    idle_contractor double precision,
    idle_neutral double precision,
    breakdown_hrs double precision,
    fuel_litres double precision,
    charged double precision,
    actual_cost double precision,
    recovery double precision,
    data text,
    ts text
);


--
-- Name: cl_eq_params; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_eq_params (
    equipment_id bigint DEFAULT bcfn.next_id('cl_eq_params'::text, 'equipment_id'::text) NOT NULL,
    planned_hours_year double precision,
    standby_rate double precision,
    market_hire_rate double precision,
    fuel_norm double precision,
    loan_id numeric,
    user_id numeric,
    ts text
);


--
-- Name: cl_forecast_override; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_forecast_override (
    project_id numeric NOT NULL,
    cost_code_id numeric NOT NULL,
    unit_cost double precision,
    note text,
    user_id numeric,
    ts text
);


--
-- Name: cl_gang_hours; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_gang_hours (
    id bigint DEFAULT bcfn.next_id('cl_gang_hours'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    dpr_labour_id numeric,
    activity_id numeric,
    idle_resp text,
    delay_id numeric,
    hours double precision DEFAULT 0,
    user_id numeric,
    ts text
);


--
-- Name: cl_health; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_health (
    period text NOT NULL,
    key text NOT NULL,
    value double precision,
    status text,
    data text,
    ts text
);


--
-- Name: cl_project; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cl_project (
    project_id bigint DEFAULT bcfn.next_id('cl_project'::text, 'project_id'::text) NOT NULL,
    coding_from text,
    pilot numeric DEFAULT 0,
    notes text,
    user_id numeric,
    ts text
);


--
-- Name: closeout_lessons; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.closeout_lessons (
    id bigint DEFAULT bcfn.next_id('closeout_lessons'::text, 'id'::text) NOT NULL,
    project_id numeric,
    category text,
    what text,
    fix text,
    owner text,
    cost_code text,
    date text,
    user_id numeric
);


--
-- Name: closeout_reviews; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.closeout_reviews (
    id bigint DEFAULT bcfn.next_id('closeout_reviews'::text, 'id'::text) NOT NULL,
    project_id numeric,
    status text DEFAULT 'open'::text,
    summary text,
    reviewed_by text,
    date text
);


--
-- Name: cm_contacts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cm_contacts (
    id bigint DEFAULT bcfn.next_id('cm_contacts'::text, 'id'::text) NOT NULL,
    project_id numeric,
    name text,
    org text,
    role text,
    phone text,
    email text,
    party_id numeric,
    notes text,
    active numeric DEFAULT 1,
    ts text
);


--
-- Name: cm_lists; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cm_lists (
    id bigint DEFAULT bcfn.next_id('cm_lists'::text, 'id'::text) NOT NULL,
    project_id numeric,
    name text,
    members text,
    active numeric DEFAULT 1,
    created_by numeric,
    ts text
);


--
-- Name: cm_notes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cm_notes (
    id bigint DEFAULT bcfn.next_id('cm_notes'::text, 'id'::text) NOT NULL,
    user_id numeric,
    kind text,
    title text,
    body text,
    link text,
    project_id numeric,
    by_user numeric,
    ts text,
    read_at text
);


--
-- Name: cm_posts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cm_posts (
    id bigint DEFAULT bcfn.next_id('cm_posts'::text, 'id'::text) NOT NULL,
    thread_id numeric,
    user_id numeric,
    body text,
    ts text,
    mentions text
);


--
-- Name: cm_reads; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cm_reads (
    thread_id numeric NOT NULL,
    user_id numeric NOT NULL,
    last_post_id numeric
);


--
-- Name: cm_threads; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cm_threads (
    id bigint DEFAULT bcfn.next_id('cm_threads'::text, 'id'::text) NOT NULL,
    project_id numeric,
    title text,
    entity text,
    entity_id numeric,
    kind text DEFAULT 'discussion'::text,
    pinned numeric DEFAULT 0,
    closed numeric DEFAULT 0,
    created_by numeric,
    ts text,
    last_ts text,
    posts numeric DEFAULT 0
);


--
-- Name: comments; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.comments (
    id bigint DEFAULT bcfn.next_id('comments'::text, 'id'::text) NOT NULL,
    entity text,
    entity_id numeric,
    user_id numeric,
    ts text,
    text text
);


--
-- Name: contract_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.contract_items (
    id bigint DEFAULT bcfn.next_id('contract_items'::text, 'id'::text) NOT NULL,
    contract_id numeric,
    kind text,
    title text,
    due_date text,
    repeat text DEFAULT 'none'::text,
    responsible text,
    direction text DEFAULT 'we_send'::text,
    status text DEFAULT 'pending'::text,
    done_date text,
    ref_no text,
    qty double precision,
    unit text,
    remarks text
);


--
-- Name: contract_milestones; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.contract_milestones (
    id bigint DEFAULT bcfn.next_id('contract_milestones'::text, 'id'::text) NOT NULL,
    project_id numeric,
    name text,
    activity_id numeric,
    due_date text,
    ld_per_day double precision DEFAULT 0,
    section text,
    remarks text
);


--
-- Name: contracts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.contracts (
    id bigint DEFAULT bcfn.next_id('contracts'::text, 'id'::text) NOT NULL,
    project_id numeric,
    party_id numeric,
    kind text,
    ref_no text,
    title text,
    value double precision DEFAULT 0,
    start_date text,
    end_date text,
    retention_pct double precision DEFAULT 0,
    advance double precision DEFAULT 0,
    bond_no text,
    bond_expiry text,
    insurance_expiry text,
    contact text,
    status text DEFAULT 'active'::text,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: cop_drafts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cop_drafts (
    id bigint DEFAULT bcfn.next_id('cop_drafts'::text, 'id'::text) NOT NULL,
    user_id numeric,
    title text,
    kind text,
    body text,
    contract_id numeric,
    project_id numeric,
    created text,
    updated text
);


--
-- Name: cop_reports; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cop_reports (
    id bigint DEFAULT bcfn.next_id('cop_reports'::text, 'id'::text) NOT NULL,
    user_id numeric,
    title text,
    question text,
    sql text,
    description text,
    chart text,
    shared numeric DEFAULT 0,
    created text,
    updated text
);


--
-- Name: cost_reviews; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cost_reviews (
    id bigint DEFAULT bcfn.next_id('cost_reviews'::text, 'id'::text) NOT NULL,
    project_id numeric,
    boq_item_id numeric,
    class text,
    revised_eac double precision,
    note text,
    user_id numeric,
    ts text
);


--
-- Name: count_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.count_lines (
    id bigint DEFAULT bcfn.next_id('count_lines'::text, 'id'::text) NOT NULL,
    count_id numeric,
    material_id numeric,
    system_qty double precision,
    counted_qty double precision,
    rate double precision,
    reason text
);


--
-- Name: cs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cs (
    id bigint DEFAULT bcfn.next_id('cs'::text, 'id'::text) NOT NULL,
    no text,
    pr_id numeric,
    project_id numeric,
    date text,
    status text DEFAULT 'draft'::text,
    recommended_vendor_id numeric,
    reason text,
    remarks text,
    po_id numeric,
    created_by numeric,
    approved_by numeric
);


--
-- Name: cs_quotes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.cs_quotes (
    id bigint DEFAULT bcfn.next_id('cs_quotes'::text, 'id'::text) NOT NULL,
    cs_id numeric,
    vendor_id numeric,
    quote_no text,
    freight double precision DEFAULT 0,
    vat_rate double precision DEFAULT 0,
    delivery_days numeric,
    payment_terms text,
    rates text
);


--
-- Name: custom_fields; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.custom_fields (
    id bigint DEFAULT bcfn.next_id('custom_fields'::text, 'id'::text) NOT NULL,
    entity text,
    label text,
    kind text DEFAULT 'text'::text,
    options text,
    sort numeric DEFAULT 0,
    active numeric DEFAULT 1,
    created_by numeric,
    created text
);


--
-- Name: custom_values; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.custom_values (
    entity text NOT NULL,
    entity_id numeric NOT NULL,
    field_id numeric NOT NULL,
    value text,
    updated_by numeric,
    updated_at text
);


--
-- Name: dep_runs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dep_runs (
    id bigint DEFAULT bcfn.next_id('dep_runs'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    month text,
    amount double precision,
    voucher_id numeric
);


--
-- Name: deployments; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.deployments (
    id bigint DEFAULT bcfn.next_id('deployments'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    project_id numeric,
    mob_date text,
    demob_date text,
    meter double precision,
    remarks text
);


--
-- Name: dm_docs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_docs (
    id bigint DEFAULT bcfn.next_id('dm_docs'::text, 'id'::text) NOT NULL,
    project_id numeric,
    folder_id numeric,
    doc_no text,
    title text,
    discipline text,
    doc_type text,
    originator text,
    status text DEFAULT 'draft'::text,
    current_rev text,
    current_rev_id numeric,
    confidential numeric DEFAULT 0,
    tags text,
    active numeric DEFAULT 1,
    created_by numeric,
    ts text,
    updated text
);


--
-- Name: dm_folders; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_folders (
    id bigint DEFAULT bcfn.next_id('dm_folders'::text, 'id'::text) NOT NULL,
    project_id numeric,
    parent_id numeric,
    name text,
    sort numeric,
    active numeric DEFAULT 1,
    ts text
);


--
-- Name: dm_reviews; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_reviews (
    id bigint DEFAULT bcfn.next_id('dm_reviews'::text, 'id'::text) NOT NULL,
    rev_id numeric,
    doc_id numeric,
    step numeric,
    reviewer_id numeric,
    due_date text,
    status text DEFAULT 'pending'::text,
    decision text,
    comment text,
    decided_on text,
    ts text
);


--
-- Name: dm_revs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_revs (
    id bigint DEFAULT bcfn.next_id('dm_revs'::text, 'id'::text) NOT NULL,
    doc_id numeric,
    rev text,
    file_id numeric,
    status text DEFAULT 'draft'::text,
    purpose text,
    note text,
    uploaded_by numeric,
    ts text,
    review_due text,
    review_mode text,
    decided_on text,
    result text
);


--
-- Name: dm_settings; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_settings (
    project_id bigint DEFAULT bcfn.next_id('dm_settings'::text, 'project_id'::text) NOT NULL,
    pattern text,
    org text
);


--
-- Name: dm_trans_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_trans_items (
    id bigint DEFAULT bcfn.next_id('dm_trans_items'::text, 'id'::text) NOT NULL,
    transmittal_id numeric,
    doc_id numeric,
    rev_id numeric,
    copies numeric DEFAULT 1,
    format text DEFAULT 'PDF'::text,
    note text
);


--
-- Name: dm_transmittals; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dm_transmittals (
    id bigint DEFAULT bcfn.next_id('dm_transmittals'::text, 'id'::text) NOT NULL,
    project_id numeric,
    no text,
    date text,
    party_id numeric,
    to_name text,
    attention text,
    list_id numeric,
    purpose text,
    subject text,
    response_due text,
    remarks text,
    status text DEFAULT 'draft'::text,
    sent_on text,
    ack_on text,
    ack_by text,
    response text,
    letter_id numeric,
    created_by numeric,
    ts text
);


--
-- Name: dpr; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dpr (
    id bigint DEFAULT bcfn.next_id('dpr'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    shift text DEFAULT 'day'::text,
    weather text,
    site_condition text,
    status text DEFAULT 'draft'::text,
    remarks text,
    version numeric DEFAULT 0,
    created_by numeric,
    submitted_by numeric,
    checked_by numeric,
    approved_by numeric,
    approved_at text,
    weather_lost_hours double precision,
    rain_mm double precision,
    lost_day numeric,
    origin text,
    origin_id numeric
);


--
-- Name: dpr_delays; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dpr_delays (
    id bigint DEFAULT bcfn.next_id('dpr_delays'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    activity_id numeric,
    category text,
    hours double precision DEFAULT 0,
    description text,
    create_event numeric DEFAULT 0,
    event_id numeric,
    responsibility text
);


--
-- Name: dpr_equipment; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dpr_equipment (
    id bigint DEFAULT bcfn.next_id('dpr_equipment'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    activity_id numeric,
    equipment_id numeric,
    operator text,
    meter_start double precision,
    meter_end double precision,
    hours double precision DEFAULT 0,
    idle_hours double precision DEFAULT 0,
    breakdown_hours double precision DEFAULT 0,
    rate double precision,
    amount double precision,
    logsheet_id numeric,
    created_log numeric DEFAULT 0,
    tool_id numeric,
    output_qty double precision
);


--
-- Name: dpr_labour; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dpr_labour (
    id bigint DEFAULT bcfn.next_id('dpr_labour'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    activity_id numeric,
    trade_id numeric,
    party_id numeric,
    count double precision DEFAULT 0,
    hours double precision DEFAULT 8,
    ot_hours double precision DEFAULT 0,
    rate double precision,
    amount double precision
);


--
-- Name: dpr_survey; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dpr_survey (
    id bigint DEFAULT bcfn.next_id('dpr_survey'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    cause text,
    trade_id numeric,
    activity_id numeric,
    area text,
    workers double precision DEFAULT 0,
    hours double precision DEFAULT 0,
    remarks text
);


--
-- Name: dpr_work; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.dpr_work (
    id bigint DEFAULT bcfn.next_id('dpr_work'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    activity_id numeric,
    boq_item_id numeric,
    location text,
    planned_qty double precision DEFAULT 0,
    actual_qty double precision DEFAULT 0,
    remarks text,
    chainage_from double precision,
    chainage_to double precision
);


--
-- Name: entity_tier; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.entity_tier (
    fy bigint DEFAULT bcfn.next_id('entity_tier'::text, 'fy'::text) NOT NULL,
    turnover double precision,
    borrowings double precision,
    total_assets double precision,
    employees double precision,
    fiduciary double precision DEFAULT 0,
    listed numeric DEFAULT 0,
    fi numeric DEFAULT 0,
    gbe numeric DEFAULT 0,
    remarks text
);


--
-- Name: eq_emi; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.eq_emi (
    id bigint DEFAULT bcfn.next_id('eq_emi'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    date text,
    amount double precision DEFAULT 0,
    principal double precision DEFAULT 0,
    interest double precision DEFAULT 0,
    bank_account_id numeric,
    voucher_id numeric,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: eq_finance; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.eq_finance (
    equipment_id bigint DEFAULT bcfn.next_id('eq_finance'::text, 'equipment_id'::text) NOT NULL,
    price double precision DEFAULT 0,
    down_payment double precision DEFAULT 0,
    loan_amount double precision DEFAULT 0,
    lender text,
    emi double precision DEFAULT 0,
    emi_count numeric DEFAULT 0,
    first_emi_date text,
    interest_rate double precision DEFAULT 0,
    life_units double precision DEFAULT 0,
    basis text DEFAULT 'hour'::text,
    output_unit text,
    market_rate double precision DEFAULT 0,
    notes text,
    ts text
);


--
-- Name: eq_tools; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.eq_tools (
    id bigint DEFAULT bcfn.next_id('eq_tools'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    name text,
    kind text,
    rate_hr double precision,
    hire_rate_hr double precision,
    fuel_hr double precision,
    output_unit text,
    norm_output_hr double precision,
    is_default numeric DEFAULT 0,
    active numeric DEFAULT 1,
    remarks text
);


--
-- Name: equipment; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.equipment (
    id bigint DEFAULT bcfn.next_id('equipment'::text, 'id'::text) NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    category text,
    make text,
    model text,
    serial text,
    reg_no text,
    ownership text DEFAULT 'owned'::text,
    vendor_id numeric,
    purchase_date text,
    purchase_value double precision DEFAULT 0,
    residual_value double precision DEFAULT 0,
    life_months numeric DEFAULT 0,
    dep_method text DEFAULT 'sl'::text,
    wdv_rate double precision DEFAULT 0,
    est_total_hours double precision DEFAULT 0,
    accumulated_dep double precision DEFAULT 0,
    meter_type text DEFAULT 'hours'::text,
    meter double precision DEFAULT 0,
    fuel_norm double precision DEFAULT 0,
    internal_rate double precision DEFAULT 0,
    insurance_expiry text,
    registration_expiry text,
    status text DEFAULT 'working'::text,
    project_id numeric,
    operator text,
    notes text,
    active numeric DEFAULT 1,
    operator_cert_no text,
    operator_cert_expiry text,
    responsible_person text,
    location text,
    last_seen text,
    lat double precision,
    lon double precision,
    meters text,
    checklist_id numeric,
    rating text,
    owner_name text
);


--
-- Name: equipment_rates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.equipment_rates (
    id bigint DEFAULT bcfn.next_id('equipment_rates'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    effective_from text,
    ownership_hr double precision DEFAULT 0,
    fuel_hr double precision DEFAULT 0,
    operator_hr double precision DEFAULT 0,
    maintenance_hr double precision DEFAULT 0,
    insurance_hr double precision DEFAULT 0,
    overhead_pct double precision DEFAULT 0,
    remarks text
);


--
-- Name: equipment_spares; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.equipment_spares (
    id bigint DEFAULT bcfn.next_id('equipment_spares'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    material_id numeric,
    qty double precision DEFAULT 1,
    remarks text
);


--
-- Name: equipment_status_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.equipment_status_log (
    id bigint DEFAULT bcfn.next_id('equipment_status_log'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    status text,
    from_ts text,
    to_ts text,
    reason text,
    user_id numeric
);


--
-- Name: events; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.events (
    id bigint DEFAULT bcfn.next_id('events'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    type text DEFAULT 'delay'::text,
    title text,
    description text,
    wbs_id numeric,
    activity_id numeric,
    dpr_id numeric,
    responsible_party text,
    clause text,
    notice_deadline text,
    delay_days double precision DEFAULT 0,
    cost_impact double precision DEFAULT 0,
    mitigation text,
    status text DEFAULT 'open'::text,
    created_by numeric,
    activity_ids text,
    notice_days double precision,
    notice_sent text,
    excusable numeric,
    compensable numeric,
    concurrent numeric,
    eot_claimed double precision,
    eot_granted double precision,
    fragnet text,
    prolongation_cost double precision,
    "window" text,
    highly_probable numeric,
    claim_value double precision,
    responsibility text
);


--
-- Name: exec_plan; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.exec_plan (
    id bigint DEFAULT bcfn.next_id('exec_plan'::text, 'id'::text) NOT NULL,
    project_id numeric,
    boq_item_id numeric,
    share_pct double precision DEFAULT 100,
    work_mode text,
    equip_mode text,
    sc_order_id numeric,
    remarks text,
    ts text
);


--
-- Name: fa_alloc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_alloc (
    id bigint DEFAULT bcfn.next_id('fa_alloc'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    month text,
    project_id numeric,
    kind text DEFAULT 'charge'::text,
    hours double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    amount double precision DEFAULT 0,
    fy text,
    voucher_id numeric,
    ts text
);


--
-- Name: fa_components; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_components (
    id bigint DEFAULT bcfn.next_id('fa_components'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    name text,
    cost double precision DEFAULT 0,
    method text DEFAULT 'SL'::text,
    life_years double precision DEFAULT 0,
    life_hours double precision DEFAULT 0,
    residual double precision DEFAULT 0,
    accumulated double precision DEFAULT 0,
    in_use_date text,
    status text DEFAULT 'active'::text,
    replaced_on text,
    remarks text
);


--
-- Name: fa_costs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_costs (
    id bigint DEFAULT bcfn.next_id('fa_costs'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    date text,
    category text,
    amount double precision DEFAULT 0,
    project_id numeric,
    ref text,
    voucher_id numeric,
    remarks text,
    user_id numeric,
    ts text
);


--
-- Name: fa_deferred; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_deferred (
    id bigint DEFAULT bcfn.next_id('fa_deferred'::text, 'id'::text) NOT NULL,
    fy text,
    carrying double precision,
    tax_base double precision,
    rate double precision,
    balance double precision,
    movement double precision,
    voucher_id numeric,
    ts text
);


--
-- Name: fa_dep; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_dep (
    id bigint DEFAULT bcfn.next_id('fa_dep'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    comp_id numeric DEFAULT 0,
    month text,
    method text,
    hours double precision DEFAULT 0,
    amount double precision DEFAULT 0,
    project_id numeric,
    voucher_id numeric,
    ts text
);


--
-- Name: fa_impair; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_impair (
    id bigint DEFAULT bcfn.next_id('fa_impair'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    date text,
    idle_days numeric,
    indicators text,
    carrying double precision,
    fvlcs double precision,
    viu double precision,
    recoverable double precision,
    loss double precision DEFAULT 0,
    voucher_id numeric,
    user_id numeric,
    remarks text
);


--
-- Name: fa_lease_rows; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_lease_rows (
    id bigint DEFAULT bcfn.next_id('fa_lease_rows'::text, 'id'::text) NOT NULL,
    lease_id numeric,
    period numeric,
    date text,
    opening double precision,
    interest double precision,
    payment double precision,
    closing double precision,
    rou_dep double precision,
    voucher_id numeric
);


--
-- Name: fa_leases; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_leases (
    id bigint DEFAULT bcfn.next_id('fa_leases'::text, 'id'::text) NOT NULL,
    no text,
    fa_id numeric,
    equipment_id numeric,
    description text,
    lessor text,
    party_id numeric,
    project_id numeric,
    start_date text,
    term_months numeric,
    payment double precision,
    periods_per_year numeric DEFAULT 12,
    rate double precision,
    in_advance numeric DEFAULT 0,
    direct_costs double precision DEFAULT 0,
    low_value numeric DEFAULT 0,
    exempt numeric DEFAULT 0,
    rou double precision DEFAULT 0,
    liability double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    voucher_id numeric,
    remarks text
);


--
-- Name: fa_maint; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_maint (
    id bigint DEFAULT bcfn.next_id('fa_maint'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    date text,
    kind text,
    at_hour double precision,
    cost double precision DEFAULT 0,
    capitalise numeric DEFAULT 0,
    comp_id numeric,
    remarks text,
    user_id numeric
);


--
-- Name: fa_rates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_rates (
    id bigint DEFAULT bcfn.next_id('fa_rates'::text, 'id'::text) NOT NULL,
    fa_id numeric,
    fy text,
    effective_from text,
    annual_hours double precision,
    params text,
    rate_hour double precision DEFAULT 0,
    dry_rate_hour double precision DEFAULT 0,
    ts text
);


--
-- Name: fa_register; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_register (
    id bigint DEFAULT bcfn.next_id('fa_register'::text, 'id'::text) NOT NULL,
    kind text,
    ref_id numeric,
    code text,
    name text,
    klass text,
    method text DEFAULT 'SL'::text,
    life_years double precision DEFAULT 0,
    life_hours double precision DEFAULT 0,
    residual double precision DEFAULT 0,
    wdv_rate double precision,
    cost double precision DEFAULT 0,
    in_use_date text,
    project_id numeric,
    tax_pool text,
    owner_entity text,
    owner_share double precision DEFAULT 100,
    lifecycle text DEFAULT 'operate'::text,
    abc_class text,
    abc_score numeric,
    s_workload numeric DEFAULT 1,
    s_impact_other numeric DEFAULT 1,
    s_impact_production numeric DEFAULT 1,
    s_repair_ease numeric DEFAULT 1,
    s_price numeric DEFAULT 1,
    idle_threshold numeric DEFAULT 90,
    managed numeric DEFAULT 1,
    accumulated double precision DEFAULT 0,
    impairment double precision DEFAULT 0,
    hour_reading double precision DEFAULT 0,
    last_service_hour double precision DEFAULT 0,
    last_inspection text,
    status text DEFAULT 'active'::text,
    disposal_date text,
    disposal_proceeds double precision DEFAULT 0,
    remarks text,
    created text
);


--
-- Name: fa_tax; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fa_tax (
    id bigint DEFAULT bcfn.next_id('fa_tax'::text, 'id'::text) NOT NULL,
    fy text,
    pool text,
    opening double precision DEFAULT 0,
    working text,
    closing double precision DEFAULT 0,
    locked numeric DEFAULT 0,
    ts text
);


--
-- Name: fc_follow; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fc_follow (
    id bigint DEFAULT bcfn.next_id('fc_follow'::text, 'id'::text) NOT NULL,
    kind text,
    ref_type text,
    ref_id numeric,
    project_id numeric,
    party_id numeric,
    note text,
    next_date text,
    promised_date text,
    promised_amount double precision,
    user_id numeric,
    user_name text,
    ts text
);


--
-- Name: fc_ipc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fc_ipc (
    ipc_id bigint DEFAULT bcfn.next_id('fc_ipc'::text, 'ipc_id'::text) NOT NULL,
    prepared_at text,
    submitted_at text,
    review_at text,
    review_by text,
    certified_at text,
    expected_pay_date text,
    responsible text,
    next_action text,
    next_action_date text,
    delay_reason text,
    client_comments text,
    updated_by numeric,
    updated_at text
);


--
-- Name: fc_ipc_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fc_ipc_log (
    id bigint DEFAULT bcfn.next_id('fc_ipc_log'::text, 'id'::text) NOT NULL,
    ipc_id numeric,
    ts text,
    user_id numeric,
    user_name text,
    kind text,
    text text
);


--
-- Name: fc_payreq; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fc_payreq (
    id bigint DEFAULT bcfn.next_id('fc_payreq'::text, 'id'::text) NOT NULL,
    no text,
    date text,
    party_id numeric,
    project_id numeric,
    category text,
    invoice_id numeric,
    po_id numeric,
    ref text,
    amount double precision DEFAULT 0,
    tax_note text,
    due_date text,
    terms text,
    proposed_date text,
    obligation text DEFAULT 'normal'::text,
    consequence text,
    deferral_reason text,
    note text,
    stage text DEFAULT 'requested'::text,
    payment_id numeric,
    voucher_id numeric,
    paid_at text,
    paid_by numeric,
    created_by numeric,
    created_at text,
    updated_at text
);


--
-- Name: fc_payreq_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fc_payreq_log (
    id bigint DEFAULT bcfn.next_id('fc_payreq_log'::text, 'id'::text) NOT NULL,
    req_id numeric,
    step text,
    action text,
    from_stage text,
    to_stage text,
    user_id numeric,
    user_name text,
    note text,
    ts text
);


--
-- Name: fcc_alert_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fcc_alert_log (
    id bigint DEFAULT bcfn.next_id('fcc_alert_log'::text, 'id'::text) NOT NULL,
    alert_id numeric NOT NULL,
    ts text NOT NULL,
    user_id numeric,
    user_name text,
    action text NOT NULL,
    from_status text,
    to_status text,
    note text,
    data text
);


--
-- Name: fcc_alerts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fcc_alerts (
    id bigint DEFAULT bcfn.next_id('fcc_alerts'::text, 'id'::text) NOT NULL,
    fkey text NOT NULL,
    kind text NOT NULL,
    domain text NOT NULL,
    project_id numeric,
    title text NOT NULL,
    detail text,
    amount double precision,
    due_date text,
    sources text,
    severity text DEFAULT 'medium'::text NOT NULL,
    basis text,
    action text,
    owner_id numeric,
    target_date text,
    status text DEFAULT 'open'::text NOT NULL,
    escalation_level numeric DEFAULT 0 NOT NULL,
    escalated_to numeric,
    escalated_at text,
    present numeric DEFAULT 1 NOT NULL,
    hold_until text,
    first_seen text,
    last_seen text,
    closed_at text,
    closed_by numeric,
    note text,
    created_at text,
    updated_at text
);


--
-- Name: fcc_fin_options; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fcc_fin_options (
    id bigint DEFAULT bcfn.next_id('fcc_fin_options'::text, 'id'::text) NOT NULL,
    name text NOT NULL,
    kind text NOT NULL,
    amount double precision NOT NULL,
    rate_pct double precision,
    fee_pct double precision,
    fee_fixed double precision,
    draw_date text NOT NULL,
    tenor_months numeric,
    repayment text DEFAULT 'bullet'::text NOT NULL,
    collateral text,
    risks text,
    notes text,
    active numeric DEFAULT 1 NOT NULL,
    created_by numeric,
    created_at text,
    updated_at text
);


--
-- Name: fcc_reports; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fcc_reports (
    id bigint DEFAULT bcfn.next_id('fcc_reports'::text, 'id'::text) NOT NULL,
    name text NOT NULL,
    dataset text NOT NULL,
    definition text NOT NULL,
    owner_id numeric,
    shared numeric DEFAULT 0 NOT NULL,
    builtin numeric DEFAULT 0 NOT NULL,
    code text,
    active numeric DEFAULT 1 NOT NULL,
    created_at text,
    updated_at text
);


--
-- Name: fcc_rules; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fcc_rules (
    kind text NOT NULL,
    enabled numeric DEFAULT 1 NOT NULL,
    threshold double precision,
    owner_role text,
    target_days numeric,
    escalate_days numeric,
    updated_by numeric,
    updated_at text
);


--
-- Name: files; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.files (
    id bigint DEFAULT bcfn.next_id('files'::text, 'id'::text) NOT NULL,
    kind text DEFAULT 'document'::text,
    entity text,
    entity_id numeric,
    project_id numeric,
    wbs_id numeric,
    activity_id numeric,
    boq_item_id numeric,
    dpr_id numeric,
    location text,
    date text,
    caption text,
    stage text,
    filename text,
    stored text,
    mime text,
    size numeric,
    user_id numeric,
    ts text
);


--
-- Name: fiscal_periods; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fiscal_periods (
    id bigint DEFAULT bcfn.next_id('fiscal_periods'::text, 'id'::text) NOT NULL,
    fy text,
    code text,
    start_date text,
    end_date text,
    status text DEFAULT 'open'::text
);


--
-- Name: fld_drawings; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_drawings (
    id bigint DEFAULT bcfn.next_id('fld_drawings'::text, 'id'::text) NOT NULL,
    project_id numeric,
    number text,
    title text,
    discipline text,
    revision text,
    rev_date text,
    status text DEFAULT 'for_construction'::text,
    file_id numeric,
    current numeric DEFAULT 1,
    transmittal text,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: fld_inspections; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_inspections (
    id bigint DEFAULT bcfn.next_id('fld_inspections'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    template_id numeric,
    title text,
    date text,
    location text,
    activity_id numeric,
    party_id numeric,
    inspector text,
    answers text,
    result text,
    failed numeric DEFAULT 0,
    remarks text,
    status text DEFAULT 'done'::text,
    created_by numeric,
    ts text
);


--
-- Name: fld_issues; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_issues (
    id bigint DEFAULT bcfn.next_id('fld_issues'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    type text,
    title text,
    description text,
    location text,
    drawing_id numeric,
    pin_x double precision,
    pin_y double precision,
    pin_page numeric,
    activity_id numeric,
    party_id numeric,
    assignee_user_id numeric,
    assignee text,
    due_date text,
    priority text DEFAULT 'normal'::text,
    status text DEFAULT 'open'::text,
    root_cause text,
    cost double precision,
    source text,
    source_id numeric,
    created_by numeric,
    ts text,
    closed_on text,
    closed_by numeric
);


--
-- Name: fld_meeting_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_meeting_items (
    id bigint DEFAULT bcfn.next_id('fld_meeting_items'::text, 'id'::text) NOT NULL,
    meeting_id numeric,
    sort numeric,
    topic text,
    discussion text,
    action text,
    owner text,
    owner_user_id numeric,
    due_date text,
    status text DEFAULT 'open'::text,
    task_id numeric,
    carried_from numeric
);


--
-- Name: fld_meetings; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_meetings (
    id bigint DEFAULT bcfn.next_id('fld_meetings'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    title text,
    kind text,
    date text,
    "time" text,
    place text,
    attendees text,
    notes text,
    status text DEFAULT 'draft'::text,
    next_date text,
    created_by numeric,
    ts text
);


--
-- Name: fld_rfis; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_rfis (
    id bigint DEFAULT bcfn.next_id('fld_rfis'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    subject text,
    question text,
    discipline text,
    location text,
    drawing_id numeric,
    spec_ref text,
    party_id numeric,
    assignee_user_id numeric,
    assignee text,
    ball_in_court text,
    due_date text,
    priority text DEFAULT 'normal'::text,
    status text DEFAULT 'open'::text,
    answer text,
    answered_by text,
    answered_on text,
    cost_impact text,
    schedule_impact text,
    event_id numeric,
    created_by numeric,
    ts text,
    sent_on text,
    closed_on text
);


--
-- Name: fld_templates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fld_templates (
    id bigint DEFAULT bcfn.next_id('fld_templates'::text, 'id'::text) NOT NULL,
    name text,
    category text,
    items text,
    active numeric DEFAULT 1,
    system numeric DEFAULT 0,
    ts text
);


--
-- Name: fy_balances; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fy_balances (
    id bigint DEFAULT bcfn.next_id('fy_balances'::text, 'id'::text) NOT NULL,
    fy text,
    account_id numeric,
    code text,
    name text,
    type text,
    opening double precision,
    debit double precision,
    credit double precision,
    closing double precision
);


--
-- Name: fy_close; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fy_close (
    id bigint DEFAULT bcfn.next_id('fy_close'::text, 'id'::text) NOT NULL,
    fy text,
    start_date text,
    end_date text,
    status text,
    profit double precision,
    closed_at text,
    closed_by numeric,
    reopened_at text,
    remarks text
);


--
-- Name: fy_stock; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.fy_stock (
    id bigint DEFAULT bcfn.next_id('fy_stock'::text, 'id'::text) NOT NULL,
    fy text,
    project_id numeric,
    store_id numeric,
    material_id numeric,
    qty double precision,
    value double precision
);


--
-- Name: grn; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.grn (
    id bigint DEFAULT bcfn.next_id('grn'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    store_id numeric,
    vendor_id numeric,
    po_id numeric,
    date text,
    challan_no text,
    vehicle_no text,
    freight double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    remarks text,
    voucher_id numeric,
    created_by numeric,
    procurement_purpose text
);


--
-- Name: grn_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.grn_lines (
    id bigint DEFAULT bcfn.next_id('grn_lines'::text, 'id'::text) NOT NULL,
    grn_id numeric,
    po_line_id numeric,
    material_id numeric,
    received_qty double precision,
    accepted_qty double precision,
    rejected_qty double precision DEFAULT 0,
    rate double precision,
    landed_rate double precision,
    invoiced_qty double precision DEFAULT 0,
    batch_no text,
    remarks text
);


--
-- Name: hire_agreements; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.hire_agreements (
    id bigint DEFAULT bcfn.next_id('hire_agreements'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    vendor_id numeric,
    project_id numeric,
    rate double precision,
    unit text DEFAULT 'hour'::text,
    min_units double precision DEFAULT 0,
    mob_cost double precision DEFAULT 0,
    vat_rate double precision DEFAULT 0,
    start_date text,
    end_date text,
    active numeric DEFAULT 1,
    remarks text,
    maint_terms text,
    fuel_terms text,
    operator_terms text
);


--
-- Name: hire_bills; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.hire_bills (
    id bigint DEFAULT bcfn.next_id('hire_bills'::text, 'id'::text) NOT NULL,
    agreement_id numeric,
    month text,
    units double precision,
    billed_units double precision,
    amount double precision,
    invoice_id numeric
);


--
-- Name: house_estimates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.house_estimates (
    id bigint DEFAULT bcfn.next_id('house_estimates'::text, 'id'::text) NOT NULL,
    no text,
    client text,
    location text,
    inputs text,
    result text,
    total double precision,
    per_sqft double precision,
    project_id numeric,
    created_by numeric,
    ts text
);


--
-- Name: hs_incidents; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.hs_incidents (
    id bigint DEFAULT bcfn.next_id('hs_incidents'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    "time" text,
    location text,
    activity_id numeric,
    kind text,
    worker_id numeric,
    person text,
    party_id numeric,
    injury text,
    days_lost double precision DEFAULT 0,
    cause text,
    description text,
    immediate_action text,
    corrective_action text,
    action_owner text,
    action_due text,
    insurance_claim text,
    reported_labour_office numeric DEFAULT 0,
    cost double precision DEFAULT 0,
    status text DEFAULT 'open'::text,
    created_by numeric,
    ts text
);


--
-- Name: hs_workers; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.hs_workers (
    id bigint DEFAULT bcfn.next_id('hs_workers'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    trade text,
    party_id numeric,
    project_id numeric,
    phone text,
    address text,
    ssf_no text,
    bank_name text,
    bank_acno text,
    insurance_policy text,
    insurance_sum double precision,
    insurance_expiry text,
    skill_cert text,
    joined text,
    left_on text,
    daily_wage double precision,
    emergency_contact text,
    active numeric DEFAULT 1,
    remarks text,
    updated text
);


--
-- Name: import_map; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.import_map (
    origin text NOT NULL,
    kind text NOT NULL,
    origin_id numeric NOT NULL,
    local_id numeric,
    pack_id numeric,
    ts text
);


--
-- Name: internal_bills; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.internal_bills (
    id bigint DEFAULT bcfn.next_id('internal_bills'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    project_id numeric,
    month text,
    hours double precision,
    rate double precision,
    amount double precision,
    voucher_id numeric
);


--
-- Name: inv_policy; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.inv_policy (
    material_id bigint DEFAULT bcfn.next_id('inv_policy'::text, 'material_id'::text) NOT NULL,
    ved text DEFAULT 'E'::text,
    lead_days double precision DEFAULT 7,
    max_lead_days double precision,
    order_cost double precision DEFAULT 0,
    carrying_pct double precision DEFAULT 0.2,
    safety double precision,
    nrv_rate double precision,
    allowed_waste_pct double precision DEFAULT 0.02,
    remarks text
);


--
-- Name: invoice_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.invoice_lines (
    id bigint DEFAULT bcfn.next_id('invoice_lines'::text, 'id'::text) NOT NULL,
    invoice_id numeric,
    grn_line_id numeric,
    material_id numeric,
    description text,
    qty double precision,
    rate double precision,
    vat_rate double precision DEFAULT 0,
    amount double precision,
    account_id numeric,
    equipment_id numeric,
    boq_item_id numeric,
    proc_alloc_id numeric
);


--
-- Name: invoices; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.invoices (
    id bigint DEFAULT bcfn.next_id('invoices'::text, 'id'::text) NOT NULL,
    no text,
    kind text,
    party_id numeric,
    project_id numeric,
    date text,
    party_inv_no text,
    due_date text,
    po_id numeric,
    subtotal double precision DEFAULT 0,
    vat double precision DEFAULT 0,
    tds double precision DEFAULT 0,
    retention double precision DEFAULT 0,
    advance_recovery double precision DEFAULT 0,
    total double precision DEFAULT 0,
    payable double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    match_status text,
    source text,
    remarks text,
    voucher_id numeric,
    created_by numeric,
    procurement_purpose text
);


--
-- Name: ipc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ipc (
    id bigint DEFAULT bcfn.next_id('ipc'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    client_id numeric,
    date text,
    period_to text,
    status text DEFAULT 'draft'::text,
    retention_pct double precision DEFAULT 0,
    tds_pct double precision DEFAULT 0,
    vat_rate double precision DEFAULT 0,
    advance_recovery double precision DEFAULT 0,
    other_deduction double precision DEFAULT 0,
    gross double precision DEFAULT 0,
    net double precision DEFAULT 0,
    invoice_id numeric,
    client_ref text,
    remarks text,
    created_by numeric,
    certified_by numeric
);


--
-- Name: ipc_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ipc_lines (
    id bigint DEFAULT bcfn.next_id('ipc_lines'::text, 'id'::text) NOT NULL,
    ipc_id numeric,
    boq_item_id numeric,
    prev_qty double precision DEFAULT 0,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    amount double precision DEFAULT 0
);


--
-- Name: issue_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.issue_lines (
    id bigint DEFAULT bcfn.next_id('issue_lines'::text, 'id'::text) NOT NULL,
    issue_id numeric,
    material_id numeric,
    qty double precision,
    rate double precision,
    amount double precision,
    target text DEFAULT 'boq'::text,
    boq_item_id numeric,
    equipment_id numeric,
    mrq_line_id numeric,
    returned_qty double precision DEFAULT 0,
    activity_id numeric
);


--
-- Name: issues; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.issues (
    id bigint DEFAULT bcfn.next_id('issues'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    store_id numeric,
    date text,
    issued_to text,
    mrq_id numeric,
    wo_id numeric,
    status text DEFAULT 'draft'::text,
    remarks text,
    voucher_id numeric,
    created_by numeric,
    origin text,
    origin_id numeric
);


--
-- Name: kpi_snapshots; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.kpi_snapshots (
    id bigint DEFAULT bcfn.next_id('kpi_snapshots'::text, 'id'::text) NOT NULL,
    project_id numeric,
    date text,
    planned_pct double precision,
    actual_pct double precision,
    spi double precision,
    cpi double precision,
    earned double precision,
    cost double precision,
    eac double precision,
    forecast_profit double precision,
    forecast_margin double precision,
    receivable double precision
);


--
-- Name: labour_burden; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.labour_burden (
    id bigint DEFAULT bcfn.next_id('labour_burden'::text, 'id'::text) NOT NULL,
    trade_id numeric,
    pay_basis text DEFAULT 'monthly'::text,
    basic double precision DEFAULT 0,
    allowance_month double precision DEFAULT 0,
    bonus_months double precision DEFAULT 1,
    ssf_employer_pct double precision DEFAULT 20,
    insurance_year double precision DEFAULT 0,
    ppe_year double precision DEFAULT 0,
    other_year double precision DEFAULT 0,
    working_days_year double precision DEFAULT 282,
    hours_day double precision DEFAULT 8,
    productive_pct double precision DEFAULT 100,
    pool_code text,
    burdened_hour double precision,
    bare_hour double precision,
    burden_pct double precision,
    applied text,
    remarks text
);


--
-- Name: loans; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.loans (
    id bigint DEFAULT bcfn.next_id('loans'::text, 'id'::text) NOT NULL,
    name text,
    lender text,
    kind text DEFAULT 'term'::text,
    emi double precision DEFAULT 0,
    start_date text,
    end_date text,
    balance double precision DEFAULT 0,
    rate double precision,
    limit_amount double precision,
    remarks text,
    active numeric DEFAULT 1
);


--
-- Name: log_checks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.log_checks (
    id bigint DEFAULT bcfn.next_id('log_checks'::text, 'id'::text) NOT NULL,
    book_id numeric,
    equipment_id numeric,
    date text,
    item text,
    result text DEFAULT 'ok'::text,
    remarks text,
    checked_by text
);


--
-- Name: log_fluids; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.log_fluids (
    id bigint DEFAULT bcfn.next_id('log_fluids'::text, 'id'::text) NOT NULL,
    book_id numeric,
    equipment_id numeric,
    date text,
    engine_oil double precision DEFAULT 0,
    gear_oil double precision DEFAULT 0,
    brake_oil double precision DEFAULT 0,
    hydraulic_oil double precision DEFAULT 0,
    transmission_oil double precision DEFAULT 0,
    crown_oil double precision DEFAULT 0,
    grease double precision DEFAULT 0,
    coolant double precision DEFAULT 0,
    other_name text,
    other_qty double precision DEFAULT 0,
    remarks text
);


--
-- Name: log_meters; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.log_meters (
    id bigint DEFAULT bcfn.next_id('log_meters'::text, 'id'::text) NOT NULL,
    log_id numeric,
    book_id numeric,
    code text,
    r_start double precision DEFAULT 0,
    r_stop double precision DEFAULT 0,
    total double precision DEFAULT 0
);


--
-- Name: log_service; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.log_service (
    id bigint DEFAULT bcfn.next_id('log_service'::text, 'id'::text) NOT NULL,
    book_id numeric,
    equipment_id numeric,
    date text,
    sn numeric,
    description text,
    part_no text,
    qty double precision DEFAULT 0,
    unit text,
    brand text,
    material_id numeric,
    issue_id numeric,
    wo_id numeric,
    at_hour double precision DEFAULT 0,
    at_km double precision DEFAULT 0,
    remarks text
);


--
-- Name: log_tools; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.log_tools (
    id bigint DEFAULT bcfn.next_id('log_tools'::text, 'id'::text) NOT NULL,
    log_id numeric,
    tool_id numeric,
    hours double precision DEFAULT 0,
    output_qty double precision,
    activity_id numeric,
    dpr_equipment_id numeric
);


--
-- Name: logbooks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.logbooks (
    id bigint DEFAULT bcfn.next_id('logbooks'::text, 'id'::text) NOT NULL,
    no text,
    equipment_id numeric,
    project_id numeric,
    period text,
    period_label text,
    from_date text,
    to_date text,
    sheet_type text DEFAULT 'owned'::text,
    owner_party_id numeric,
    owner_name text,
    hirer_party_id numeric,
    hirer_name text,
    operator text,
    operator2 text,
    site text,
    location text,
    cost_code text,
    meters text,
    checklist_id numeric,
    rate double precision DEFAULT 0,
    rate_basis text,
    payable_days double precision,
    payable_hours double precision,
    remarks text,
    issues text,
    status text DEFAULT 'draft'::text,
    prepared_by numeric,
    checked_by numeric,
    approved_by numeric,
    approved_on text,
    created_by numeric,
    origin text,
    origin_id numeric
);


--
-- Name: login_attempts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.login_attempts (
    id bigint DEFAULT bcfn.next_id('login_attempts'::text, 'id'::text) NOT NULL,
    ts text,
    username text,
    ip text,
    ok numeric
);


--
-- Name: logsheets; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.logsheets (
    id bigint DEFAULT bcfn.next_id('logsheets'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    project_id numeric,
    date text,
    shift text DEFAULT 'day'::text,
    operator text,
    meter_start double precision,
    meter_end double precision,
    hours double precision DEFAULT 0,
    idle_hours double precision DEFAULT 0,
    breakdown_hours double precision DEFAULT 0,
    boq_item_id numeric,
    work text,
    trips double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    approved_by numeric,
    created_by numeric,
    dpr_id numeric,
    activity_id numeric,
    origin text,
    origin_id numeric,
    book_id numeric,
    time_start text,
    time_stop text,
    fuel_qty double precision,
    fuel_req_no text,
    standby_hours double precision,
    down_reason text,
    cost_code text,
    sign_store text,
    sign_operator text,
    sign_incharge text,
    sign_hirer text,
    km_start double precision,
    km_end double precision,
    km_run double precision
);


--
-- Name: lookahead; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.lookahead (
    id bigint DEFAULT bcfn.next_id('lookahead'::text, 'id'::text) NOT NULL,
    project_id numeric,
    week_start text,
    activity_id numeric,
    planned_qty double precision DEFAULT 0,
    foreman text,
    done numeric,
    actual_qty double precision,
    reason text,
    checks text,
    created text
);


--
-- Name: maint_plans; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.maint_plans (
    id bigint DEFAULT bcfn.next_id('maint_plans'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    title text,
    interval_type text DEFAULT 'days'::text,
    "interval" double precision,
    last_date text,
    last_meter double precision DEFAULT 0,
    checklist text,
    active numeric DEFAULT 1
);


--
-- Name: mat_causes; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mat_causes (
    id bigint DEFAULT bcfn.next_id('mat_causes'::text, 'id'::text) NOT NULL,
    project_id numeric,
    boq_item_id numeric,
    material_id numeric,
    month text,
    kind text DEFAULT 'wastage'::text,
    cause text,
    qty double precision,
    value double precision,
    note text,
    user_id numeric,
    ts text
);


--
-- Name: material_coefficients; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.material_coefficients (
    id bigint DEFAULT bcfn.next_id('material_coefficients'::text, 'id'::text) NOT NULL,
    boq_item_id numeric,
    material_id numeric,
    qty_per_unit double precision,
    wastage_pct double precision DEFAULT 0
);


--
-- Name: materials; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.materials (
    id bigint DEFAULT bcfn.next_id('materials'::text, 'id'::text) NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    local_name text,
    category text,
    unit text,
    spec text,
    min_level double precision DEFAULT 0,
    reorder_level double precision DEFAULT 0,
    reorder_qty double precision DEFAULT 0,
    lead_days numeric DEFAULT 0,
    standard_rate double precision DEFAULT 0,
    batch_tracked numeric DEFAULT 0,
    active numeric DEFAULT 1,
    kind text
);


--
-- Name: maturity_checks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.maturity_checks (
    id bigint DEFAULT bcfn.next_id('maturity_checks'::text, 'id'::text) NOT NULL,
    year text,
    stage text,
    qkey text,
    score numeric,
    note text
);


--
-- Name: measurement_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.measurement_lines (
    id bigint DEFAULT bcfn.next_id('measurement_lines'::text, 'id'::text) NOT NULL,
    measurement_id numeric,
    boq_item_id numeric,
    qty double precision,
    location text,
    remarks text
);


--
-- Name: measurements; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.measurements (
    id bigint DEFAULT bcfn.next_id('measurements'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    status text DEFAULT 'draft'::text,
    remarks text,
    verified_by numeric,
    created_by numeric
);


--
-- Name: mg_tags; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mg_tags (
    line_id bigint DEFAULT bcfn.next_id('mg_tags'::text, 'line_id'::text) NOT NULL,
    voucher_id numeric,
    mode text,
    segment text,
    how text DEFAULT 'auto'::text,
    user_id numeric,
    ts text
);


--
-- Name: mh_meta; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mh_meta (
    k text NOT NULL,
    v text
);


--
-- Name: mh_sheets; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mh_sheets (
    id bigint DEFAULT bcfn.next_id('mh_sheets'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    capacity text,
    category text,
    params text,
    res_code text,
    equipment_id numeric,
    book_id numeric,
    rate double precision,
    breakdown text,
    source text,
    active numeric DEFAULT 1,
    remarks text,
    created_by numeric,
    ts text,
    updated text
);


--
-- Name: mix_designs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mix_designs (
    id bigint DEFAULT bcfn.next_id('mix_designs'::text, 'id'::text) NOT NULL,
    plant_id numeric,
    code text,
    name text,
    output_material_id numeric,
    output_qty double precision DEFAULT 1,
    unit text,
    grade text,
    approved_by text,
    approved_date text,
    remarks text,
    active numeric DEFAULT 1
);


--
-- Name: mix_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mix_lines (
    id bigint DEFAULT bcfn.next_id('mix_lines'::text, 'id'::text) NOT NULL,
    mix_id numeric,
    material_id numeric,
    qty_per_unit double precision DEFAULT 0,
    wastage_pct double precision DEFAULT 0,
    remarks text
);


--
-- Name: mrq; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mrq (
    id bigint DEFAULT bcfn.next_id('mrq'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    store_id numeric,
    requested_by text,
    status text DEFAULT 'draft'::text,
    remarks text,
    auto numeric DEFAULT 0,
    created_by numeric,
    approved_by numeric
);


--
-- Name: mrq_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.mrq_lines (
    id bigint DEFAULT bcfn.next_id('mrq_lines'::text, 'id'::text) NOT NULL,
    mrq_id numeric,
    material_id numeric,
    qty double precision,
    approved_qty double precision,
    issued_qty double precision DEFAULT 0,
    pr_qty double precision DEFAULT 0,
    boq_item_id numeric,
    remarks text
);


--
-- Name: ncrs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ncrs (
    id bigint DEFAULT bcfn.next_id('ncrs'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    title text,
    description text,
    activity_id numeric,
    test_id numeric,
    corrective_action text,
    due_date text,
    status text DEFAULT 'open'::text,
    closed_date text,
    created_by numeric
);


--
-- Name: nfrs18_map; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.nfrs18_map (
    account_id bigint DEFAULT bcfn.next_id('nfrs18_map'::text, 'account_id'::text) NOT NULL,
    category text
);


--
-- Name: oh_budget; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.oh_budget (
    id bigint DEFAULT bcfn.next_id('oh_budget'::text, 'id'::text) NOT NULL,
    fy numeric,
    category text,
    account_id numeric,
    kind text DEFAULT 'fixed'::text,
    month numeric,
    amount double precision DEFAULT 0
);


--
-- Name: operator_violations; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.operator_violations (
    id bigint DEFAULT bcfn.next_id('operator_violations'::text, 'id'::text) NOT NULL,
    date text,
    equipment_id numeric,
    operator text,
    violation text,
    penalty double precision DEFAULT 0,
    action text,
    remarks text,
    user_id numeric
);


--
-- Name: pa_formula; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.pa_formula (
    project_id bigint DEFAULT bcfn.next_id('pa_formula'::text, 'project_id'::text) NOT NULL,
    base_period text,
    fixed_a double precision DEFAULT 0.15,
    coeffs text,
    start_after_months numeric DEFAULT 0,
    remarks text,
    updated text
);


--
-- Name: pa_indices; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.pa_indices (
    id bigint DEFAULT bcfn.next_id('pa_indices'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    period text,
    value double precision,
    source text,
    updated text
);


--
-- Name: parties; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.parties (
    id bigint DEFAULT bcfn.next_id('parties'::text, 'id'::text) NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    kind text NOT NULL,
    pan text,
    vat_registered numeric DEFAULT 0,
    phone text,
    email text,
    address text,
    bank text,
    bank_acno text,
    credit_days numeric DEFAULT 30,
    categories text,
    blacklisted numeric DEFAULT 0,
    active numeric DEFAULT 1,
    notes text
);


--
-- Name: payments; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.payments (
    id bigint DEFAULT bcfn.next_id('payments'::text, 'id'::text) NOT NULL,
    no text,
    kind text,
    party_id numeric,
    project_id numeric,
    date text,
    bank_account_id numeric,
    gross double precision,
    tds double precision DEFAULT 0,
    tds_rate_id numeric,
    net double precision,
    advance double precision DEFAULT 0,
    mode text,
    cheque_no text,
    status text DEFAULT 'posted'::text,
    remarks text,
    voucher_id numeric,
    created_by numeric,
    funding_purpose text
);


--
-- Name: plant_run_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.plant_run_lines (
    id bigint DEFAULT bcfn.next_id('plant_run_lines'::text, 'id'::text) NOT NULL,
    run_id numeric,
    material_id numeric,
    planned_qty double precision DEFAULT 0,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    amount double precision DEFAULT 0
);


--
-- Name: plant_runs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.plant_runs (
    id bigint DEFAULT bcfn.next_id('plant_runs'::text, 'id'::text) NOT NULL,
    no text,
    plant_id numeric,
    project_id numeric,
    date text,
    shift text DEFAULT 'day'::text,
    mix_id numeric,
    store_id numeric,
    output_material_id numeric,
    output_qty double precision DEFAULT 0,
    rejected_qty double precision DEFAULT 0,
    run_hours double precision DEFAULT 0,
    down_hours double precision DEFAULT 0,
    down_reason text,
    power_units double precision DEFAULT 0,
    diesel_qty double precision DEFAULT 0,
    labour_cost double precision DEFAULT 0,
    boq_item_id numeric,
    activity_id numeric,
    dpr_id numeric,
    material_cost double precision DEFAULT 0,
    other_cost double precision DEFAULT 0,
    total_cost double precision DEFAULT 0,
    unit_cost double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    voucher_id numeric,
    issue_id numeric,
    remarks text,
    operator text,
    created_by numeric,
    approved_by numeric
);


--
-- Name: plant_tests; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.plant_tests (
    id bigint DEFAULT bcfn.next_id('plant_tests'::text, 'id'::text) NOT NULL,
    run_id numeric,
    plant_id numeric,
    date text,
    test_type text,
    sample_ref text,
    result_value text,
    criteria text,
    status text DEFAULT 'pending'::text,
    remarks text
);


--
-- Name: plants; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.plants (
    id bigint DEFAULT bcfn.next_id('plants'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    kind text DEFAULT 'batching'::text,
    project_id numeric,
    location text,
    capacity double precision DEFAULT 0,
    capacity_unit text,
    output_material_id numeric,
    equipment_id numeric,
    power_kw double precision DEFAULT 0,
    operator text,
    commissioned text,
    notes text,
    active numeric DEFAULT 1
);


--
-- Name: po; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.po (
    id bigint DEFAULT bcfn.next_id('po'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    vendor_id numeric,
    date text,
    delivery_date text,
    store_id numeric,
    pr_id numeric,
    cs_id numeric,
    payment_terms text,
    freight double precision DEFAULT 0,
    subtotal double precision DEFAULT 0,
    vat double precision DEFAULT 0,
    total double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    revision numeric DEFAULT 0,
    terms text,
    remarks text,
    created_by numeric,
    approved_by numeric,
    approved_at text,
    close_reason text
);


--
-- Name: po_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.po_lines (
    id bigint DEFAULT bcfn.next_id('po_lines'::text, 'id'::text) NOT NULL,
    po_id numeric,
    pr_line_id numeric,
    material_id numeric,
    description text,
    qty double precision,
    unit text,
    rate double precision,
    vat_rate double precision DEFAULT 0,
    received_qty double precision DEFAULT 0,
    boq_item_id numeric
);


--
-- Name: po_revisions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.po_revisions (
    id bigint DEFAULT bcfn.next_id('po_revisions'::text, 'id'::text) NOT NULL,
    po_id numeric,
    revision numeric,
    snapshot text,
    reason text,
    ts text,
    user_id numeric
);


--
-- Name: post_queue; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.post_queue (
    voucher_id bigint DEFAULT bcfn.next_id('post_queue'::text, 'voucher_id'::text) NOT NULL,
    source text,
    source_id numeric,
    gate text,
    module text,
    stage text DEFAULT 'review'::text,
    label text,
    project_id numeric,
    amount double precision DEFAULT 0,
    vtype text,
    created_by numeric,
    created_at text,
    approved_by numeric,
    approved_at text,
    note text,
    returned_by numeric,
    returned_at text,
    posted_by numeric,
    posted_at text,
    posted_no text
);


--
-- Name: pr; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.pr (
    id bigint DEFAULT bcfn.next_id('pr'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    date text,
    required_by text,
    source text DEFAULT 'manual'::text,
    mrq_id numeric,
    status text DEFAULT 'draft'::text,
    priority text DEFAULT 'normal'::text,
    remarks text,
    created_by numeric,
    approved_by numeric
);


--
-- Name: pr_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.pr_lines (
    id bigint DEFAULT bcfn.next_id('pr_lines'::text, 'id'::text) NOT NULL,
    pr_id numeric,
    material_id numeric,
    description text,
    qty double precision,
    unit text,
    est_rate double precision DEFAULT 0,
    boq_item_id numeric,
    ordered_qty double precision DEFAULT 0,
    mrq_line_id numeric
);


--
-- Name: proc_adjust; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.proc_adjust (
    id bigint DEFAULT bcfn.next_id('proc_adjust'::text, 'id'::text) NOT NULL,
    no text,
    date text,
    kind text,
    grn_id numeric,
    grn_line_id numeric,
    invoice_id numeric,
    material_id numeric,
    qty double precision DEFAULT 0,
    value double precision DEFAULT 0,
    net double precision DEFAULT 0,
    vat double precision DEFAULT 0,
    from_purpose text,
    from_project numeric,
    from_store numeric,
    to_purpose text,
    to_project numeric,
    to_store numeric,
    voucher_id numeric,
    reason text,
    created_by numeric,
    ts text
);


--
-- Name: proc_alloc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.proc_alloc (
    id bigint DEFAULT bcfn.next_id('proc_alloc'::text, 'id'::text) NOT NULL,
    grn_id numeric,
    grn_line_id numeric,
    material_id numeric,
    purpose text,
    project_id numeric,
    store_id numeric,
    boq_item_id numeric,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    landed_rate double precision DEFAULT 0,
    value double precision DEFAULT 0,
    status text DEFAULT 'draft'::text,
    kind text DEFAULT 'receipt'::text,
    adjust_id numeric,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: proc_inv_alloc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.proc_inv_alloc (
    id bigint DEFAULT bcfn.next_id('proc_inv_alloc'::text, 'id'::text) NOT NULL,
    invoice_id numeric,
    invoice_line_id numeric,
    grn_line_id numeric,
    purpose text,
    project_id numeric,
    store_id numeric,
    qty double precision DEFAULT 0,
    net double precision DEFAULT 0,
    vat_rate double precision DEFAULT 0,
    vat double precision DEFAULT 0,
    rounding double precision DEFAULT 0,
    method text,
    status text DEFAULT 'posted'::text,
    adjust_id numeric,
    ts text
);


--
-- Name: proc_pay_alloc; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.proc_pay_alloc (
    id bigint DEFAULT bcfn.next_id('proc_pay_alloc'::text, 'id'::text) NOT NULL,
    payment_id numeric,
    allocation_id numeric,
    invoice_id numeric,
    purpose text,
    project_id numeric,
    funding_purpose text,
    funding_project_id numeric,
    amount double precision DEFAULT 0,
    kind text DEFAULT 'payment'::text,
    active numeric DEFAULT 1,
    ts text
);


--
-- Name: projects; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.projects (
    id bigint DEFAULT bcfn.next_id('projects'::text, 'id'::text) NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    client text,
    location text,
    contract_value double precision DEFAULT 0,
    start_date text,
    end_date text,
    status text DEFAULT 'active'::text,
    ntp_date text,
    tfc_days double precision,
    tfc_basis text,
    completion_date text,
    ld_per_day double precision,
    ld_cap_pct double precision,
    notice_days double precision,
    float_owner text,
    near_crit_days double precision,
    calendar_id numeric,
    indirect_per_day double precision,
    time_notes text,
    data_date text,
    cert_days double precision,
    pay_days double precision,
    ipc_cycle_days double precision,
    retention_pct double precision,
    retention_release_pct double precision,
    dlp_months double precision,
    advance_pct double precision,
    advance_recovery_pct double precision,
    vat_pct double precision,
    tds_pct double precision,
    supplier_credit_days double precision,
    labour_pay_days double precision,
    subcon_pct double precision,
    project_type text,
    pm_name text,
    contract_type text,
    sec26 numeric,
    performance_obligations text,
    jv_share_pct double precision,
    jv_partners text,
    mgmt_hours double precision,
    revenue_method text,
    built_area_sqft double precision,
    licence_class text,
    kind text
);


--
-- Name: prov_moves; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.prov_moves (
    id bigint DEFAULT bcfn.next_id('prov_moves'::text, 'id'::text) NOT NULL,
    provision_id numeric,
    date text,
    kind text,
    amount double precision,
    voucher_id numeric,
    note text,
    user_id numeric
);


--
-- Name: provisions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.provisions (
    id bigint DEFAULT bcfn.next_id('provisions'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    kind text,
    title text,
    date text,
    amount double precision DEFAULT 0,
    probability text,
    basis text,
    status text DEFAULT 'open'::text,
    voucher_id numeric,
    reversed_voucher_id numeric,
    remarks text,
    created_by numeric
);


--
-- Name: qa_tests; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.qa_tests (
    id bigint DEFAULT bcfn.next_id('qa_tests'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    activity_id numeric,
    boq_item_id numeric,
    material_id numeric,
    dpr_id numeric,
    location text,
    test_type text,
    sample_ref text,
    sampled_date text,
    result_date text,
    result_value text,
    criteria text,
    status text DEFAULT 'pending'::text,
    ncr_id numeric,
    remarks text,
    created_by numeric
);


--
-- Name: ra_analyses; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ra_analyses (
    id bigint DEFAULT bcfn.next_id('ra_analyses'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    boq_item_id numeric,
    norm_id numeric,
    book_id numeric,
    title text,
    unit text,
    overhead_pct double precision,
    vat_pct double precision,
    leads text,
    result text,
    cost_per_unit double precision,
    rate_ex_vat double precision,
    rate_incl_vat double precision,
    status text DEFAULT 'draft'::text,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: ra_norm_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ra_norm_lines (
    id bigint DEFAULT bcfn.next_id('ra_norm_lines'::text, 'id'::text) NOT NULL,
    norm_id numeric,
    sort numeric,
    kind text,
    ref text,
    qty double precision DEFAULT 0,
    note text
);


--
-- Name: ra_norms; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ra_norms (
    id bigint DEFAULT bcfn.next_id('ra_norms'::text, 'id'::text) NOT NULL,
    code text,
    source text,
    section text,
    title text,
    unit text,
    per_qty double precision DEFAULT 1,
    remarks text,
    derivation text,
    verified numeric DEFAULT 0,
    system numeric DEFAULT 0,
    active numeric DEFAULT 1,
    copied_from text,
    updated text,
    ref_rate double precision,
    checks text
);


--
-- Name: ra_seed_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ra_seed_log (
    tag text NOT NULL,
    ts text,
    info text
);


--
-- Name: rate_analysis; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.rate_analysis (
    id bigint DEFAULT bcfn.next_id('rate_analysis'::text, 'id'::text) NOT NULL,
    boq_item_id numeric,
    kind text,
    ref_id numeric,
    description text,
    qty_per_unit double precision DEFAULT 0,
    rate double precision DEFAULT 0
);


--
-- Name: rate_books; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.rate_books (
    id bigint DEFAULT bcfn.next_id('rate_books'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    district text,
    fy text,
    source text,
    is_default numeric DEFAULT 0,
    active numeric DEFAULT 1,
    remarks text
);


--
-- Name: rent_deductions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.rent_deductions (
    id bigint DEFAULT bcfn.next_id('rent_deductions'::text, 'id'::text) NOT NULL,
    agreement_id numeric,
    equipment_id numeric,
    date text,
    kind text,
    description text,
    amount double precision DEFAULT 0,
    account_id numeric,
    source text,
    source_id numeric,
    invoice_id numeric,
    status text DEFAULT 'open'::text,
    created_by numeric,
    ts text
);


--
-- Name: res_pool; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.res_pool (
    id bigint DEFAULT bcfn.next_id('res_pool'::text, 'id'::text) NOT NULL,
    code text,
    type text,
    category text,
    subcategory text,
    name text,
    spec text,
    unit text,
    weight double precision DEFAULT 0,
    rate double precision,
    rate_source text,
    sample numeric DEFAULT 0,
    system numeric DEFAULT 0,
    active numeric DEFAULT 1,
    local_table text,
    local_id numeric,
    remarks text,
    updated text
);


--
-- Name: res_rates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.res_rates (
    id bigint DEFAULT bcfn.next_id('res_rates'::text, 'id'::text) NOT NULL,
    book_id numeric,
    res_id numeric,
    rate double precision,
    source text,
    updated text
);


--
-- Name: return_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.return_lines (
    id bigint DEFAULT bcfn.next_id('return_lines'::text, 'id'::text) NOT NULL,
    return_id numeric,
    material_id numeric,
    issue_line_id numeric,
    qty double precision,
    condition text DEFAULT 'usable'::text,
    rate double precision,
    amount double precision,
    boq_item_id numeric,
    equipment_id numeric
);


--
-- Name: returns; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.returns (
    id bigint DEFAULT bcfn.next_id('returns'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    store_id numeric,
    date text,
    returned_by text,
    status text DEFAULT 'draft'::text,
    remarks text,
    voucher_id numeric,
    created_by numeric
);


--
-- Name: risks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.risks (
    id bigint DEFAULT bcfn.next_id('risks'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    title text,
    category text,
    cause text,
    effect text,
    owner text,
    probability numeric DEFAULT 3,
    impact numeric DEFAULT 3,
    cost_impact double precision DEFAULT 0,
    time_impact_days double precision DEFAULT 0,
    response text DEFAULT 'reduce'::text,
    action text,
    due_date text,
    status text DEFAULT 'open'::text,
    created_by numeric,
    created text,
    updated text
);


--
-- Name: sa_moves; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sa_moves (
    id bigint DEFAULT bcfn.next_id('sa_moves'::text, 'id'::text) NOT NULL,
    pool_id numeric,
    project_id numeric,
    date text,
    kind text,
    qty double precision DEFAULT 0,
    value double precision DEFAULT 0,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: sa_pools; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sa_pools (
    id bigint DEFAULT bcfn.next_id('sa_pools'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    class text,
    unit text,
    qty double precision DEFAULT 0,
    cost double precision DEFAULT 0,
    life_months numeric DEFAULT 36,
    residual_pct double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    rate_basis text DEFAULT 'day'::text,
    purchase_date text,
    active numeric DEFAULT 1,
    notes text
);


--
-- Name: sa_runs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sa_runs (
    id bigint DEFAULT bcfn.next_id('sa_runs'::text, 'id'::text) NOT NULL,
    month text,
    pool_id numeric,
    project_id numeric,
    unit_days double precision DEFAULT 0,
    amount double precision DEFAULT 0,
    voucher_id numeric,
    ts text
);


--
-- Name: safety_checks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.safety_checks (
    id bigint DEFAULT bcfn.next_id('safety_checks'::text, 'id'::text) NOT NULL,
    equipment_id numeric,
    date text,
    result text DEFAULT 'pass'::text,
    checked_by text,
    notes text,
    next_due text
);


--
-- Name: sc_bill_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_bill_items (
    id bigint DEFAULT bcfn.next_id('sc_bill_items'::text, 'id'::text) NOT NULL,
    bill_id numeric,
    order_item_id numeric,
    prev_qty double precision DEFAULT 0,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    amount double precision DEFAULT 0
);


--
-- Name: sc_bill_recoveries; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_bill_recoveries (
    id bigint DEFAULT bcfn.next_id('sc_bill_recoveries'::text, 'id'::text) NOT NULL,
    bill_id numeric,
    kind text,
    material_id numeric,
    equipment_id numeric,
    description text,
    qty double precision DEFAULT 0,
    cost_rate double precision DEFAULT 0,
    cost double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    amount double precision DEFAULT 0
);


--
-- Name: sc_bills; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_bills (
    id bigint DEFAULT bcfn.next_id('sc_bills'::text, 'id'::text) NOT NULL,
    no text,
    order_id numeric,
    project_id numeric,
    party_id numeric,
    date text,
    period_to text,
    party_bill_no text,
    status text DEFAULT 'draft'::text,
    gross double precision DEFAULT 0,
    material_recovery double precision DEFAULT 0,
    material_cost double precision DEFAULT 0,
    equipment_recovery double precision DEFAULT 0,
    other_deduction double precision DEFAULT 0,
    advance_recovery double precision DEFAULT 0,
    retention double precision DEFAULT 0,
    vat double precision DEFAULT 0,
    net double precision DEFAULT 0,
    invoice_id numeric,
    remarks text,
    note text,
    created_by numeric,
    submitted_by numeric,
    approved_by numeric,
    posted_by numeric,
    ts text
);


--
-- Name: sc_moves; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_moves (
    id bigint DEFAULT bcfn.next_id('sc_moves'::text, 'id'::text) NOT NULL,
    no text,
    order_id numeric,
    project_id numeric,
    store_id numeric,
    date text,
    kind text,
    material_id numeric,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0,
    value double precision DEFAULT 0,
    voucher_id numeric,
    status text DEFAULT 'posted'::text,
    remarks text,
    created_by numeric,
    ts text
);


--
-- Name: sc_order_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_order_items (
    id bigint DEFAULT bcfn.next_id('sc_order_items'::text, 'id'::text) NOT NULL,
    order_id numeric,
    boq_item_id numeric,
    description text,
    unit text,
    qty double precision DEFAULT 0,
    rate double precision DEFAULT 0
);


--
-- Name: sc_order_mats; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_order_mats (
    id bigint DEFAULT bcfn.next_id('sc_order_mats'::text, 'id'::text) NOT NULL,
    order_id numeric,
    material_id numeric,
    order_item_id numeric,
    per_unit double precision DEFAULT 0,
    wastage_pct double precision DEFAULT 0,
    fixed_rate double precision DEFAULT 0
);


--
-- Name: sc_orders; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sc_orders (
    id bigint DEFAULT bcfn.next_id('sc_orders'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    party_id numeric,
    type text,
    title text,
    date text,
    start_date text,
    end_date text,
    retention_pct double precision DEFAULT 0,
    advance double precision DEFAULT 0,
    vat_rate double precision DEFAULT 0,
    recovery_basis text DEFAULT 'bill_oh'::text,
    overhead_pct double precision DEFAULT 0,
    equip_terms text,
    status text DEFAULT 'draft'::text,
    contract_id numeric,
    remarks text,
    created_by numeric,
    approved_by numeric,
    ts text
);


--
-- Name: sched_baseline_acts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sched_baseline_acts (
    id bigint DEFAULT bcfn.next_id('sched_baseline_acts'::text, 'id'::text) NOT NULL,
    baseline_id numeric,
    activity_id numeric,
    start text,
    finish text,
    dur double precision,
    tf double precision,
    value double precision,
    planned_qty double precision,
    critical numeric DEFAULT 0
);


--
-- Name: sched_baselines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sched_baselines (
    id bigint DEFAULT bcfn.next_id('sched_baselines'::text, 'id'::text) NOT NULL,
    project_id numeric,
    no numeric,
    name text,
    data_date text,
    start text,
    finish text,
    created text,
    created_by numeric,
    is_current numeric DEFAULT 0,
    notes text
);


--
-- Name: sched_calendars; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sched_calendars (
    id bigint DEFAULT bcfn.next_id('sched_calendars'::text, 'id'::text) NOT NULL,
    project_id numeric,
    name text,
    week text DEFAULT '1111101'::text,
    hours_day double precision DEFAULT 8,
    is_default numeric DEFAULT 0,
    weather text,
    notes text
);


--
-- Name: sched_holidays; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sched_holidays (
    id bigint DEFAULT bcfn.next_id('sched_holidays'::text, 'id'::text) NOT NULL,
    calendar_id numeric,
    date text,
    name text,
    kind text DEFAULT 'public'::text
);


--
-- Name: sched_runs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sched_runs (
    id bigint DEFAULT bcfn.next_id('sched_runs'::text, 'id'::text) NOT NULL,
    project_id numeric,
    data_date text,
    start text,
    finish text,
    prev_finish text,
    target text,
    critical_count numeric,
    warnings text,
    snapshot text,
    created text,
    user_id numeric,
    notes text
);


--
-- Name: sched_windows; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sched_windows (
    id bigint DEFAULT bcfn.next_id('sched_windows'::text, 'id'::text) NOT NULL,
    calendar_id numeric,
    work_type text,
    bs_from text,
    bs_to text,
    reason text
);


--
-- Name: sequences; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sequences (
    doc_type text NOT NULL,
    fy text NOT NULL,
    next numeric
);


--
-- Name: sessions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.sessions (
    token text NOT NULL,
    user_id numeric,
    created text,
    ws text,
    ws_project numeric,
    last_seen text,
    ip text,
    device text
);


--
-- Name: settings; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.settings (
    key text NOT NULL,
    value text
);


--
-- Name: site_mode_cfg; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.site_mode_cfg (
    scope text NOT NULL,
    items text,
    updated text,
    user_id numeric
);


--
-- Name: site_packs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.site_packs (
    id bigint DEFAULT bcfn.next_id('site_packs'::text, 'id'::text) NOT NULL,
    ts text,
    direction text,
    site_code text,
    filename text,
    project_id numeric,
    counts text,
    note text,
    user_id numeric
);


--
-- Name: sqlite_master; Type: VIEW; Schema: buildcore; Owner: -
--

CREATE VIEW buildcore.sqlite_master AS
 SELECT
        CASE c.relkind
            WHEN 'v'::"char" THEN 'view'::text
            WHEN 'i'::"char" THEN 'index'::text
            ELSE 'table'::text
        END AS type,
    (c.relname)::text AS name,
    (COALESCE(t.relname, c.relname))::text AS tbl_name,
    0 AS rootpage,
        CASE
            WHEN (c.relkind = 'v'::"char") THEN ((('CREATE VIEW '::text || (c.relname)::text) || ' AS '::text) || pg_get_viewdef(c.oid))
            WHEN (c.relkind = 'i'::"char") THEN pg_get_indexdef(c.oid)
            ELSE (('CREATE TABLE '::text || (c.relname)::text) || '(...)'::text)
        END AS sql
   FROM (((pg_class c
     JOIN pg_namespace n ON ((n.oid = c.relnamespace)))
     LEFT JOIN pg_index ix ON ((ix.indexrelid = c.oid)))
     LEFT JOIN pg_class t ON ((t.oid = ix.indrelid)))
  WHERE ((n.nspname = 'buildcore'::name) AND (c.relkind = ANY (ARRAY['r'::"char", 'p'::"char", 'v'::"char", 'i'::"char"])) AND (c.relname <> 'sqlite_master'::name))
UNION ALL
 SELECT 'trigger'::text AS type,
    (tg.tgname)::text AS name,
    (c.relname)::text AS tbl_name,
    0 AS rootpage,
    NULL::text AS sql
   FROM ((pg_trigger tg
     JOIN pg_class c ON ((c.oid = tg.tgrelid)))
     JOIN pg_namespace n ON ((n.oid = c.relnamespace)))
  WHERE ((n.nspname = 'buildcore'::name) AND (NOT tg.tgisinternal));


--
-- Name: staff; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.staff (
    id bigint DEFAULT bcfn.next_id('staff'::text, 'id'::text) NOT NULL,
    code text,
    name text NOT NULL,
    designation text,
    phone text,
    daily_rate double precision,
    monthly_rate double precision,
    project_id numeric,
    active numeric DEFAULT 1
);


--
-- Name: stock_balances; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.stock_balances (
    project_id numeric NOT NULL,
    store_id numeric NOT NULL,
    material_id numeric NOT NULL,
    qty double precision DEFAULT 0,
    value double precision DEFAULT 0,
    last_date text
);


--
-- Name: stock_counts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.stock_counts (
    id bigint DEFAULT bcfn.next_id('stock_counts'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    store_id numeric,
    date text,
    status text DEFAULT 'draft'::text,
    remarks text,
    voucher_id numeric,
    created_by numeric
);


--
-- Name: stock_ledger; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.stock_ledger (
    id bigint DEFAULT bcfn.next_id('stock_ledger'::text, 'id'::text) NOT NULL,
    date text,
    project_id numeric,
    store_id numeric,
    material_id numeric,
    doc_type text,
    doc_id numeric,
    doc_no text,
    qty_in double precision DEFAULT 0,
    qty_out double precision DEFAULT 0,
    rate double precision,
    value_in double precision DEFAULT 0,
    value_out double precision DEFAULT 0,
    batch_no text,
    created_by numeric,
    ts text
);


--
-- Name: stores; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.stores (
    id bigint DEFAULT bcfn.next_id('stores'::text, 'id'::text) NOT NULL,
    project_id numeric NOT NULL,
    code text,
    name text,
    type text DEFAULT 'sub'::text,
    parent_id numeric,
    keeper text,
    active numeric DEFAULT 1
);


--
-- Name: submittals; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.submittals (
    id bigint DEFAULT bcfn.next_id('submittals'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    kind text DEFAULT 'drawing'::text,
    title text,
    ref text,
    activity_id numeric,
    required_by text,
    submitted_date text,
    review_days numeric DEFAULT 14,
    due_back text,
    returned_date text,
    status text DEFAULT 'planned'::text,
    revision text,
    party text,
    remarks text,
    created_by numeric
);


--
-- Name: tasks; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.tasks (
    id bigint DEFAULT bcfn.next_id('tasks'::text, 'id'::text) NOT NULL,
    project_id numeric,
    title text,
    description text,
    due_date text,
    priority text DEFAULT 'normal'::text,
    status text DEFAULT 'open'::text,
    assigned_to numeric,
    source_type text,
    source_id numeric,
    created_by numeric,
    ts text,
    done_at text
);


--
-- Name: tds_rates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.tds_rates (
    id bigint DEFAULT bcfn.next_id('tds_rates'::text, 'id'::text) NOT NULL,
    section text,
    description text,
    rate double precision,
    threshold double precision DEFAULT 0,
    active numeric DEFAULT 1
);


--
-- Name: tds_rates_fy; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.tds_rates_fy (
    id bigint DEFAULT bcfn.next_id('tds_rates_fy'::text, 'id'::text) NOT NULL,
    fy numeric,
    section text,
    description text,
    rate double precision,
    threshold double precision DEFAULT 0,
    final numeric DEFAULT 0,
    notes text
);


--
-- Name: trade_moves; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.trade_moves (
    id bigint DEFAULT bcfn.next_id('trade_moves'::text, 'id'::text) NOT NULL,
    no text,
    kind text,
    date text,
    invoice_id numeric,
    sale_move_id numeric,
    party_id numeric,
    project_id numeric,
    store_id numeric,
    material_id numeric,
    qty double precision DEFAULT 0,
    price double precision DEFAULT 0,
    vat_rate double precision DEFAULT 0,
    net double precision DEFAULT 0,
    vat double precision DEFAULT 0,
    cost_rate double precision DEFAULT 0,
    cost_value double precision DEFAULT 0,
    voucher_id numeric,
    cn_voucher_id numeric,
    returned_qty double precision DEFAULT 0,
    status text DEFAULT 'posted'::text,
    reason text,
    created_by numeric,
    ts text
);


--
-- Name: trades; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.trades (
    id bigint DEFAULT bcfn.next_id('trades'::text, 'id'::text) NOT NULL,
    project_id numeric,
    code text,
    name text,
    rate_hour double precision DEFAULT 0,
    active numeric DEFAULT 1,
    base_rate_hour double precision,
    burden_pct double precision
);


--
-- Name: transfer_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.transfer_lines (
    id bigint DEFAULT bcfn.next_id('transfer_lines'::text, 'id'::text) NOT NULL,
    transfer_id numeric,
    material_id numeric,
    qty double precision,
    rate double precision,
    received_qty double precision DEFAULT 0
);


--
-- Name: transfers; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.transfers (
    id bigint DEFAULT bcfn.next_id('transfers'::text, 'id'::text) NOT NULL,
    no text,
    from_project numeric,
    from_store numeric,
    to_project numeric,
    to_store numeric,
    date text,
    received_date text,
    status text DEFAULT 'draft'::text,
    vehicle_no text,
    remarks text,
    voucher_id numeric,
    created_by numeric
);


--
-- Name: udpr_fronts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_fronts (
    id bigint DEFAULT bcfn.next_id('udpr_fronts'::text, 'id'::text) NOT NULL,
    project_id numeric,
    kind text DEFAULT 'front'::text,
    code text,
    name text,
    parent_id numeric,
    party_id numeric,
    contract_id numeric,
    discipline text,
    location text,
    ch_from double precision,
    ch_to double precision,
    active numeric DEFAULT 1,
    sort numeric DEFAULT 0,
    ts text
);


--
-- Name: udpr_head; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_head (
    dpr_id bigint DEFAULT bcfn.next_id('udpr_head'::text, 'dpr_id'::text) NOT NULL,
    package_id numeric,
    front_id numeric,
    temp_min double precision,
    temp_max double precision,
    humidity double precision,
    conditions text,
    prepared_name text,
    checked_name text,
    approved_name text,
    s_work text,
    s_achieve text,
    s_activities text,
    s_problems text,
    s_instructions text,
    s_decisions text,
    s_next text,
    tpl_versions text,
    submitted_at text,
    checked_at text,
    returned_at text,
    returned_by numeric,
    return_comment text,
    rejected_at text,
    rejected_by numeric,
    reject_reason text,
    locked_at text,
    locked_by numeric,
    revision numeric DEFAULT 0,
    client_token text,
    created_at text,
    updated_at text
);


--
-- Name: udpr_issue_days; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_issue_days (
    issue_id numeric NOT NULL,
    dpr_id numeric NOT NULL,
    date text,
    hours double precision DEFAULT 0,
    note text
);


--
-- Name: udpr_issue_x; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_issue_x (
    issue_id bigint DEFAULT bcfn.next_id('udpr_issue_x'::text, 'issue_id'::text) NOT NULL,
    category text,
    front_id numeric,
    impact text,
    mitigation text,
    decision_required text,
    claim_relevant numeric DEFAULT 0,
    responsible_party text,
    event_id numeric,
    first_dpr_id numeric,
    first_date text,
    last_dpr_id numeric,
    last_date text,
    days_reported numeric DEFAULT 0,
    hours_total double precision DEFAULT 0
);


--
-- Name: udpr_layouts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_layouts (
    id bigint DEFAULT bcfn.next_id('udpr_layouts'::text, 'id'::text) NOT NULL,
    name text,
    kind text,
    params text,
    owner_id numeric,
    shared numeric DEFAULT 1,
    ts text
);


--
-- Name: udpr_log; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_log (
    id bigint DEFAULT bcfn.next_id('udpr_log'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    action text,
    from_status text,
    to_status text,
    user_id numeric,
    user_name text,
    comment text,
    ts text
);


--
-- Name: udpr_lx; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_lx (
    part text NOT NULL,
    line_id numeric NOT NULL,
    dpr_id numeric,
    front_id numeric,
    vals text
);


--
-- Name: udpr_project; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_project (
    project_id bigint DEFAULT bcfn.next_id('udpr_project'::text, 'project_id'::text) NOT NULL,
    templates text,
    hidden text,
    sections text,
    progress_basis text DEFAULT 'reported'::text,
    basis_from text,
    scope_tol double precision DEFAULT 0,
    updated_by numeric,
    updated_at text
);


--
-- Name: udpr_revisions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_revisions (
    id bigint DEFAULT bcfn.next_id('udpr_revisions'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    rev_no numeric,
    kind text,
    reason text,
    snapshot text,
    user_id numeric,
    ts text
);


--
-- Name: udpr_rows; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_rows (
    id bigint DEFAULT bcfn.next_id('udpr_rows'::text, 'id'::text) NOT NULL,
    dpr_id numeric,
    section text,
    row_no numeric,
    front_id numeric,
    data text,
    created_by numeric,
    ts text
);


--
-- Name: udpr_templates; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_templates (
    id bigint DEFAULT bcfn.next_id('udpr_templates'::text, 'id'::text) NOT NULL,
    code text,
    name text,
    category text,
    description text,
    project_id numeric,
    system numeric DEFAULT 0,
    active numeric DEFAULT 1,
    draft text,
    current_version_id numeric,
    updated_by numeric,
    updated_at text
);


--
-- Name: udpr_tpl_versions; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_tpl_versions (
    id bigint DEFAULT bcfn.next_id('udpr_tpl_versions'::text, 'id'::text) NOT NULL,
    template_id numeric,
    version_no numeric,
    definition text,
    note text,
    published_by numeric,
    published_at text
);


--
-- Name: udpr_values; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_values (
    dpr_id numeric NOT NULL,
    key text NOT NULL,
    value text
);


--
-- Name: udpr_work; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.udpr_work (
    work_id bigint DEFAULT bcfn.next_id('udpr_work'::text, 'work_id'::text) NOT NULL,
    dpr_id numeric,
    front_id numeric,
    package_id numeric,
    accepted_qty double precision,
    accepted_by numeric,
    accepted_at text,
    accept_note text,
    over_scope_by numeric,
    over_scope_reason text,
    delay_reason text,
    vals text
);


--
-- Name: user_shortcuts; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.user_shortcuts (
    id bigint DEFAULT bcfn.next_id('user_shortcuts'::text, 'id'::text) NOT NULL,
    user_id numeric,
    combo text,
    kind text,
    target text,
    label text,
    everyone numeric DEFAULT 0,
    created text
);


--
-- Name: users; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.users (
    id bigint DEFAULT bcfn.next_id('users'::text, 'id'::text) NOT NULL,
    username text NOT NULL,
    name text,
    pw_hash text,
    salt text,
    role text NOT NULL,
    active numeric DEFAULT 1,
    ws_default text,
    project_ids text,
    location text,
    phone text,
    email text,
    created text
);


--
-- Name: variations; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.variations (
    id bigint DEFAULT bcfn.next_id('variations'::text, 'id'::text) NOT NULL,
    no text,
    project_id numeric,
    boq_item_id numeric,
    new_code text,
    new_description text,
    new_unit text,
    date text,
    title text,
    reason text,
    instruction_ref text,
    var_qty double precision DEFAULT 0,
    new_rate double precision,
    time_impact_days double precision DEFAULT 0,
    event_id numeric,
    status text DEFAULT 'identified'::text,
    approved_date text,
    created_by numeric,
    highly_probable numeric,
    est_value double precision
);


--
-- Name: vendor_ratings; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.vendor_ratings (
    id bigint DEFAULT bcfn.next_id('vendor_ratings'::text, 'id'::text) NOT NULL,
    vendor_id numeric,
    po_id numeric,
    quality numeric,
    delivery numeric,
    price numeric,
    service numeric,
    remarks text,
    date text
);


--
-- Name: verify_items; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.verify_items (
    id bigint DEFAULT bcfn.next_id('verify_items'::text, 'id'::text) NOT NULL,
    round_id numeric,
    kind text,
    ref_id numeric,
    found numeric DEFAULT 1,
    location text,
    condition text,
    notes text,
    by text,
    ts text
);


--
-- Name: verify_rounds; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.verify_rounds (
    id bigint DEFAULT bcfn.next_id('verify_rounds'::text, 'id'::text) NOT NULL,
    name text,
    date text,
    status text DEFAULT 'open'::text,
    remarks text
);


--
-- Name: voucher_lines; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.voucher_lines (
    id bigint DEFAULT bcfn.next_id('voucher_lines'::text, 'id'::text) NOT NULL,
    voucher_id numeric,
    account_id numeric,
    debit double precision DEFAULT 0,
    credit double precision DEFAULT 0,
    narration text,
    project_id numeric,
    boq_item_id numeric,
    equipment_id numeric,
    party_id numeric,
    cleared_date text,
    activity_id numeric,
    wbs_id numeric
);


--
-- Name: vouchers; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.vouchers (
    id bigint DEFAULT bcfn.next_id('vouchers'::text, 'id'::text) NOT NULL,
    no text,
    type text,
    date text,
    project_id numeric,
    narration text,
    status text,
    source text,
    source_id numeric,
    reversal_of numeric,
    party_id numeric,
    ref_no text,
    total double precision,
    created_by numeric,
    approved_by numeric,
    ts text
);


--
-- Name: wbs; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.wbs (
    id bigint DEFAULT bcfn.next_id('wbs'::text, 'id'::text) NOT NULL,
    project_id numeric NOT NULL,
    code text,
    name text,
    parent_id numeric,
    weight double precision DEFAULT 0,
    sort numeric DEFAULT 0
);


--
-- Name: web_kv; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.web_kv (
    name text NOT NULL,
    value text,
    ts text
);


--
-- Name: work_orders; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.work_orders (
    id bigint DEFAULT bcfn.next_id('work_orders'::text, 'id'::text) NOT NULL,
    no text,
    equipment_id numeric,
    project_id numeric,
    plan_id numeric,
    type text DEFAULT 'breakdown'::text,
    status text DEFAULT 'open'::text,
    reported_at text,
    started_at text,
    completed_at text,
    description text,
    action_taken text,
    downtime_hours double precision DEFAULT 0,
    meter double precision,
    technician text,
    created_by numeric,
    failure_code text,
    cause_detail text,
    idle_crew double precision,
    crew_rate_hour double precision,
    idle_linked_cost_hour double precision,
    activity_id numeric,
    ld_applied double precision,
    downtime_cost double precision,
    source text,
    source_ref text,
    parts_cost double precision,
    labour_cost double precision,
    external_cost double precision,
    workshop text,
    parts_replaced text,
    repair_remarks text
);


--
-- Name: ws_roles; Type: TABLE; Schema: buildcore; Owner: -
--

CREATE TABLE buildcore.ws_roles (
    id bigint DEFAULT bcfn.next_id('ws_roles'::text, 'id'::text) NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    company numeric DEFAULT 0,
    projects text DEFAULT 'none'::text,
    perms text,
    builtin numeric DEFAULT 0,
    active numeric DEFAULT 1,
    sort numeric DEFAULT 0
);


--
-- Name: account_groups account_groups_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.account_groups
    ADD CONSTRAINT account_groups_code_key UNIQUE (code);


--
-- Name: account_groups account_groups_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.account_groups
    ADD CONSTRAINT account_groups_pkey PRIMARY KEY (id);


--
-- Name: accounts accounts_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.accounts
    ADD CONSTRAINT accounts_code_key UNIQUE (code);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: act_links act_links_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.act_links
    ADD CONSTRAINT act_links_pkey PRIMARY KEY (id);


--
-- Name: act_resources act_resources_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.act_resources
    ADD CONSTRAINT act_resources_pkey PRIMARY KEY (id);


--
-- Name: activities activities_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (id);


--
-- Name: activity activity_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.activity
    ADD CONSTRAINT activity_pkey PRIMARY KEY (id);


--
-- Name: ai_config ai_config_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ai_config
    ADD CONSTRAINT ai_config_pkey PRIMARY KEY (key);


--
-- Name: ai_doc_pages ai_doc_pages_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ai_doc_pages
    ADD CONSTRAINT ai_doc_pages_pkey PRIMARY KEY (doc_id, page);


--
-- Name: ai_docs ai_docs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ai_docs
    ADD CONSTRAINT ai_docs_pkey PRIMARY KEY (id);


--
-- Name: ai_items ai_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ai_items
    ADD CONSTRAINT ai_items_pkey PRIMARY KEY (id);


--
-- Name: ai_log ai_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ai_log
    ADD CONSTRAINT ai_log_pkey PRIMARY KEY (id);


--
-- Name: allocations allocations_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.allocations
    ADD CONSTRAINT allocations_pkey PRIMARY KEY (id);


--
-- Name: asset_acq asset_acq_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.asset_acq
    ADD CONSTRAINT asset_acq_pkey PRIMARY KEY (id);


--
-- Name: asset_cases asset_cases_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.asset_cases
    ADD CONSTRAINT asset_cases_pkey PRIMARY KEY (id);


--
-- Name: asset_disposals asset_disposals_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.asset_disposals
    ADD CONSTRAINT asset_disposals_pkey PRIMARY KEY (id);


--
-- Name: asset_moves asset_moves_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.asset_moves
    ADD CONSTRAINT asset_moves_pkey PRIMARY KEY (id);


--
-- Name: assets assets_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.assets
    ADD CONSTRAINT assets_code_key UNIQUE (code);


--
-- Name: assets assets_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.assets
    ADD CONSTRAINT assets_pkey PRIMARY KEY (id);


--
-- Name: audit audit_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.audit
    ADD CONSTRAINT audit_pkey PRIMARY KEY (id);


--
-- Name: bid_prices bid_prices_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.bid_prices
    ADD CONSTRAINT bid_prices_pkey PRIMARY KEY (id);


--
-- Name: bids bids_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.bids
    ADD CONSTRAINT bids_pkey PRIMARY KEY (id);


--
-- Name: boq_components boq_components_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.boq_components
    ADD CONSTRAINT boq_components_pkey PRIMARY KEY (id);


--
-- Name: boq_items boq_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.boq_items
    ADD CONSTRAINT boq_items_pkey PRIMARY KEY (id);


--
-- Name: budgets budgets_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.budgets
    ADD CONSTRAINT budgets_pkey PRIMARY KEY (id);


--
-- Name: ca_clauses ca_clauses_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ca_clauses
    ADD CONSTRAINT ca_clauses_pkey PRIMARY KEY (id);


--
-- Name: ca_letters ca_letters_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ca_letters
    ADD CONSTRAINT ca_letters_pkey PRIMARY KEY (id);


--
-- Name: ca_securities ca_securities_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ca_securities
    ADD CONSTRAINT ca_securities_pkey PRIMARY KEY (id);


--
-- Name: ca_timebars ca_timebars_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ca_timebars
    ADD CONSTRAINT ca_timebars_pkey PRIMARY KEY (id);


--
-- Name: cfw_items cfw_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cfw_items
    ADD CONSTRAINT cfw_items_pkey PRIMARY KEY (id);


--
-- Name: cfw_restricted cfw_restricted_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cfw_restricted
    ADD CONSTRAINT cfw_restricted_pkey PRIMARY KEY (id);


--
-- Name: cfw_snapshots cfw_snapshots_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cfw_snapshots
    ADD CONSTRAINT cfw_snapshots_pkey PRIMARY KEY (id);


--
-- Name: check_lists check_lists_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.check_lists
    ADD CONSTRAINT check_lists_code_key UNIQUE (code);


--
-- Name: check_lists check_lists_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.check_lists
    ADD CONSTRAINT check_lists_pkey PRIMARY KEY (id);


--
-- Name: cl_alloc cl_alloc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_alloc
    ADD CONSTRAINT cl_alloc_pkey PRIMARY KEY (line_id, cost_code_id);


--
-- Name: cl_budget_changes cl_budget_changes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_budget_changes
    ADD CONSTRAINT cl_budget_changes_pkey PRIMARY KEY (id);


--
-- Name: cl_budget_lines cl_budget_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_budget_lines
    ADD CONSTRAINT cl_budget_lines_pkey PRIMARY KEY (id);


--
-- Name: cl_budget_versions cl_budget_versions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_budget_versions
    ADD CONSTRAINT cl_budget_versions_pkey PRIMARY KEY (id);


--
-- Name: cl_close_accruals cl_close_accruals_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_close_accruals
    ADD CONSTRAINT cl_close_accruals_pkey PRIMARY KEY (id);


--
-- Name: cl_close_checks cl_close_checks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_close_checks
    ADD CONSTRAINT cl_close_checks_pkey PRIMARY KEY (close_id, check_no);


--
-- Name: cl_close_lines cl_close_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_close_lines
    ADD CONSTRAINT cl_close_lines_pkey PRIMARY KEY (close_id, cost_code_id);


--
-- Name: cl_close_qty cl_close_qty_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_close_qty
    ADD CONSTRAINT cl_close_qty_pkey PRIMARY KEY (close_id, boq_item_id);


--
-- Name: cl_close_reopen_log cl_close_reopen_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_close_reopen_log
    ADD CONSTRAINT cl_close_reopen_log_pkey PRIMARY KEY (id);


--
-- Name: cl_close_scqty cl_close_scqty_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_close_scqty
    ADD CONSTRAINT cl_close_scqty_pkey PRIMARY KEY (close_id, order_item_id);


--
-- Name: cl_closes cl_closes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_closes
    ADD CONSTRAINT cl_closes_pkey PRIMARY KEY (id);


--
-- Name: cl_closes cl_closes_project_id_period_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_closes
    ADD CONSTRAINT cl_closes_project_id_period_key UNIQUE (project_id, period);


--
-- Name: cl_codes cl_codes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_codes
    ADD CONSTRAINT cl_codes_pkey PRIMARY KEY (id);


--
-- Name: cl_doc_codes cl_doc_codes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_doc_codes
    ADD CONSTRAINT cl_doc_codes_pkey PRIMARY KEY (doc, line_id);


--
-- Name: cl_eq_months cl_eq_months_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_eq_months
    ADD CONSTRAINT cl_eq_months_pkey PRIMARY KEY (equipment_id, period);


--
-- Name: cl_eq_params cl_eq_params_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_eq_params
    ADD CONSTRAINT cl_eq_params_pkey PRIMARY KEY (equipment_id);


--
-- Name: cl_forecast_override cl_forecast_override_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_forecast_override
    ADD CONSTRAINT cl_forecast_override_pkey PRIMARY KEY (project_id, cost_code_id);


--
-- Name: cl_gang_hours cl_gang_hours_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_gang_hours
    ADD CONSTRAINT cl_gang_hours_pkey PRIMARY KEY (id);


--
-- Name: cl_health cl_health_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_health
    ADD CONSTRAINT cl_health_pkey PRIMARY KEY (period, key);


--
-- Name: cl_project cl_project_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cl_project
    ADD CONSTRAINT cl_project_pkey PRIMARY KEY (project_id);


--
-- Name: closeout_lessons closeout_lessons_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.closeout_lessons
    ADD CONSTRAINT closeout_lessons_pkey PRIMARY KEY (id);


--
-- Name: closeout_reviews closeout_reviews_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.closeout_reviews
    ADD CONSTRAINT closeout_reviews_pkey PRIMARY KEY (id);


--
-- Name: closeout_reviews closeout_reviews_project_id_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.closeout_reviews
    ADD CONSTRAINT closeout_reviews_project_id_key UNIQUE (project_id);


--
-- Name: cm_contacts cm_contacts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cm_contacts
    ADD CONSTRAINT cm_contacts_pkey PRIMARY KEY (id);


--
-- Name: cm_lists cm_lists_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cm_lists
    ADD CONSTRAINT cm_lists_pkey PRIMARY KEY (id);


--
-- Name: cm_notes cm_notes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cm_notes
    ADD CONSTRAINT cm_notes_pkey PRIMARY KEY (id);


--
-- Name: cm_posts cm_posts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cm_posts
    ADD CONSTRAINT cm_posts_pkey PRIMARY KEY (id);


--
-- Name: cm_reads cm_reads_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cm_reads
    ADD CONSTRAINT cm_reads_pkey PRIMARY KEY (thread_id, user_id);


--
-- Name: cm_threads cm_threads_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cm_threads
    ADD CONSTRAINT cm_threads_pkey PRIMARY KEY (id);


--
-- Name: comments comments_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.comments
    ADD CONSTRAINT comments_pkey PRIMARY KEY (id);


--
-- Name: contract_items contract_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.contract_items
    ADD CONSTRAINT contract_items_pkey PRIMARY KEY (id);


--
-- Name: contract_milestones contract_milestones_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.contract_milestones
    ADD CONSTRAINT contract_milestones_pkey PRIMARY KEY (id);


--
-- Name: contracts contracts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.contracts
    ADD CONSTRAINT contracts_pkey PRIMARY KEY (id);


--
-- Name: cop_drafts cop_drafts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cop_drafts
    ADD CONSTRAINT cop_drafts_pkey PRIMARY KEY (id);


--
-- Name: cop_reports cop_reports_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cop_reports
    ADD CONSTRAINT cop_reports_pkey PRIMARY KEY (id);


--
-- Name: cost_reviews cost_reviews_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cost_reviews
    ADD CONSTRAINT cost_reviews_pkey PRIMARY KEY (id);


--
-- Name: count_lines count_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.count_lines
    ADD CONSTRAINT count_lines_pkey PRIMARY KEY (id);


--
-- Name: cs cs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cs
    ADD CONSTRAINT cs_pkey PRIMARY KEY (id);


--
-- Name: cs_quotes cs_quotes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.cs_quotes
    ADD CONSTRAINT cs_quotes_pkey PRIMARY KEY (id);


--
-- Name: custom_fields custom_fields_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.custom_fields
    ADD CONSTRAINT custom_fields_pkey PRIMARY KEY (id);


--
-- Name: custom_values custom_values_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.custom_values
    ADD CONSTRAINT custom_values_pkey PRIMARY KEY (entity, entity_id, field_id);


--
-- Name: dep_runs dep_runs_equipment_id_month_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dep_runs
    ADD CONSTRAINT dep_runs_equipment_id_month_key UNIQUE (equipment_id, month);


--
-- Name: dep_runs dep_runs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dep_runs
    ADD CONSTRAINT dep_runs_pkey PRIMARY KEY (id);


--
-- Name: deployments deployments_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.deployments
    ADD CONSTRAINT deployments_pkey PRIMARY KEY (id);


--
-- Name: dm_docs dm_docs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_docs
    ADD CONSTRAINT dm_docs_pkey PRIMARY KEY (id);


--
-- Name: dm_folders dm_folders_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_folders
    ADD CONSTRAINT dm_folders_pkey PRIMARY KEY (id);


--
-- Name: dm_reviews dm_reviews_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_reviews
    ADD CONSTRAINT dm_reviews_pkey PRIMARY KEY (id);


--
-- Name: dm_revs dm_revs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_revs
    ADD CONSTRAINT dm_revs_pkey PRIMARY KEY (id);


--
-- Name: dm_settings dm_settings_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_settings
    ADD CONSTRAINT dm_settings_pkey PRIMARY KEY (project_id);


--
-- Name: dm_trans_items dm_trans_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_trans_items
    ADD CONSTRAINT dm_trans_items_pkey PRIMARY KEY (id);


--
-- Name: dm_transmittals dm_transmittals_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dm_transmittals
    ADD CONSTRAINT dm_transmittals_pkey PRIMARY KEY (id);


--
-- Name: dpr_delays dpr_delays_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr_delays
    ADD CONSTRAINT dpr_delays_pkey PRIMARY KEY (id);


--
-- Name: dpr_equipment dpr_equipment_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr_equipment
    ADD CONSTRAINT dpr_equipment_pkey PRIMARY KEY (id);


--
-- Name: dpr_labour dpr_labour_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr_labour
    ADD CONSTRAINT dpr_labour_pkey PRIMARY KEY (id);


--
-- Name: dpr dpr_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr
    ADD CONSTRAINT dpr_pkey PRIMARY KEY (id);


--
-- Name: dpr dpr_project_id_date_shift_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr
    ADD CONSTRAINT dpr_project_id_date_shift_key UNIQUE (project_id, date, shift);


--
-- Name: dpr_survey dpr_survey_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr_survey
    ADD CONSTRAINT dpr_survey_pkey PRIMARY KEY (id);


--
-- Name: dpr_work dpr_work_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.dpr_work
    ADD CONSTRAINT dpr_work_pkey PRIMARY KEY (id);


--
-- Name: entity_tier entity_tier_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.entity_tier
    ADD CONSTRAINT entity_tier_pkey PRIMARY KEY (fy);


--
-- Name: eq_emi eq_emi_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.eq_emi
    ADD CONSTRAINT eq_emi_pkey PRIMARY KEY (id);


--
-- Name: eq_finance eq_finance_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.eq_finance
    ADD CONSTRAINT eq_finance_pkey PRIMARY KEY (equipment_id);


--
-- Name: eq_tools eq_tools_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.eq_tools
    ADD CONSTRAINT eq_tools_pkey PRIMARY KEY (id);


--
-- Name: equipment equipment_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.equipment
    ADD CONSTRAINT equipment_code_key UNIQUE (code);


--
-- Name: equipment equipment_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.equipment
    ADD CONSTRAINT equipment_pkey PRIMARY KEY (id);


--
-- Name: equipment_rates equipment_rates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.equipment_rates
    ADD CONSTRAINT equipment_rates_pkey PRIMARY KEY (id);


--
-- Name: equipment_spares equipment_spares_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.equipment_spares
    ADD CONSTRAINT equipment_spares_pkey PRIMARY KEY (id);


--
-- Name: equipment_status_log equipment_status_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.equipment_status_log
    ADD CONSTRAINT equipment_status_log_pkey PRIMARY KEY (id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: exec_plan exec_plan_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.exec_plan
    ADD CONSTRAINT exec_plan_pkey PRIMARY KEY (id);


--
-- Name: fa_alloc fa_alloc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_alloc
    ADD CONSTRAINT fa_alloc_pkey PRIMARY KEY (id);


--
-- Name: fa_components fa_components_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_components
    ADD CONSTRAINT fa_components_pkey PRIMARY KEY (id);


--
-- Name: fa_costs fa_costs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_costs
    ADD CONSTRAINT fa_costs_pkey PRIMARY KEY (id);


--
-- Name: fa_deferred fa_deferred_fy_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_deferred
    ADD CONSTRAINT fa_deferred_fy_key UNIQUE (fy);


--
-- Name: fa_deferred fa_deferred_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_deferred
    ADD CONSTRAINT fa_deferred_pkey PRIMARY KEY (id);


--
-- Name: fa_dep fa_dep_fa_id_comp_id_month_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_dep
    ADD CONSTRAINT fa_dep_fa_id_comp_id_month_key UNIQUE (fa_id, comp_id, month);


--
-- Name: fa_dep fa_dep_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_dep
    ADD CONSTRAINT fa_dep_pkey PRIMARY KEY (id);


--
-- Name: fa_impair fa_impair_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_impair
    ADD CONSTRAINT fa_impair_pkey PRIMARY KEY (id);


--
-- Name: fa_lease_rows fa_lease_rows_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_lease_rows
    ADD CONSTRAINT fa_lease_rows_pkey PRIMARY KEY (id);


--
-- Name: fa_leases fa_leases_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_leases
    ADD CONSTRAINT fa_leases_pkey PRIMARY KEY (id);


--
-- Name: fa_maint fa_maint_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_maint
    ADD CONSTRAINT fa_maint_pkey PRIMARY KEY (id);


--
-- Name: fa_rates fa_rates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_rates
    ADD CONSTRAINT fa_rates_pkey PRIMARY KEY (id);


--
-- Name: fa_register fa_register_kind_ref_id_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_register
    ADD CONSTRAINT fa_register_kind_ref_id_key UNIQUE (kind, ref_id);


--
-- Name: fa_register fa_register_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_register
    ADD CONSTRAINT fa_register_pkey PRIMARY KEY (id);


--
-- Name: fa_tax fa_tax_fy_pool_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_tax
    ADD CONSTRAINT fa_tax_fy_pool_key UNIQUE (fy, pool);


--
-- Name: fa_tax fa_tax_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fa_tax
    ADD CONSTRAINT fa_tax_pkey PRIMARY KEY (id);


--
-- Name: fc_follow fc_follow_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fc_follow
    ADD CONSTRAINT fc_follow_pkey PRIMARY KEY (id);


--
-- Name: fc_ipc_log fc_ipc_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fc_ipc_log
    ADD CONSTRAINT fc_ipc_log_pkey PRIMARY KEY (id);


--
-- Name: fc_ipc fc_ipc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fc_ipc
    ADD CONSTRAINT fc_ipc_pkey PRIMARY KEY (ipc_id);


--
-- Name: fc_payreq_log fc_payreq_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fc_payreq_log
    ADD CONSTRAINT fc_payreq_log_pkey PRIMARY KEY (id);


--
-- Name: fc_payreq fc_payreq_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fc_payreq
    ADD CONSTRAINT fc_payreq_pkey PRIMARY KEY (id);


--
-- Name: fcc_alert_log fcc_alert_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fcc_alert_log
    ADD CONSTRAINT fcc_alert_log_pkey PRIMARY KEY (id);


--
-- Name: fcc_alerts fcc_alerts_fkey_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fcc_alerts
    ADD CONSTRAINT fcc_alerts_fkey_key UNIQUE (fkey);


--
-- Name: fcc_alerts fcc_alerts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fcc_alerts
    ADD CONSTRAINT fcc_alerts_pkey PRIMARY KEY (id);


--
-- Name: fcc_fin_options fcc_fin_options_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fcc_fin_options
    ADD CONSTRAINT fcc_fin_options_pkey PRIMARY KEY (id);


--
-- Name: fcc_reports fcc_reports_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fcc_reports
    ADD CONSTRAINT fcc_reports_pkey PRIMARY KEY (id);


--
-- Name: fcc_rules fcc_rules_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fcc_rules
    ADD CONSTRAINT fcc_rules_pkey PRIMARY KEY (kind);


--
-- Name: files files_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.files
    ADD CONSTRAINT files_pkey PRIMARY KEY (id);


--
-- Name: fiscal_periods fiscal_periods_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fiscal_periods
    ADD CONSTRAINT fiscal_periods_code_key UNIQUE (code);


--
-- Name: fiscal_periods fiscal_periods_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fiscal_periods
    ADD CONSTRAINT fiscal_periods_pkey PRIMARY KEY (id);


--
-- Name: fld_drawings fld_drawings_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_drawings
    ADD CONSTRAINT fld_drawings_pkey PRIMARY KEY (id);


--
-- Name: fld_inspections fld_inspections_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_inspections
    ADD CONSTRAINT fld_inspections_pkey PRIMARY KEY (id);


--
-- Name: fld_issues fld_issues_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_issues
    ADD CONSTRAINT fld_issues_pkey PRIMARY KEY (id);


--
-- Name: fld_meeting_items fld_meeting_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_meeting_items
    ADD CONSTRAINT fld_meeting_items_pkey PRIMARY KEY (id);


--
-- Name: fld_meetings fld_meetings_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_meetings
    ADD CONSTRAINT fld_meetings_pkey PRIMARY KEY (id);


--
-- Name: fld_rfis fld_rfis_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_rfis
    ADD CONSTRAINT fld_rfis_pkey PRIMARY KEY (id);


--
-- Name: fld_templates fld_templates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fld_templates
    ADD CONSTRAINT fld_templates_pkey PRIMARY KEY (id);


--
-- Name: fy_balances fy_balances_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fy_balances
    ADD CONSTRAINT fy_balances_pkey PRIMARY KEY (id);


--
-- Name: fy_close fy_close_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fy_close
    ADD CONSTRAINT fy_close_pkey PRIMARY KEY (id);


--
-- Name: fy_stock fy_stock_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.fy_stock
    ADD CONSTRAINT fy_stock_pkey PRIMARY KEY (id);


--
-- Name: grn_lines grn_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.grn_lines
    ADD CONSTRAINT grn_lines_pkey PRIMARY KEY (id);


--
-- Name: grn grn_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.grn
    ADD CONSTRAINT grn_pkey PRIMARY KEY (id);


--
-- Name: hire_agreements hire_agreements_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.hire_agreements
    ADD CONSTRAINT hire_agreements_pkey PRIMARY KEY (id);


--
-- Name: hire_bills hire_bills_agreement_id_month_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.hire_bills
    ADD CONSTRAINT hire_bills_agreement_id_month_key UNIQUE (agreement_id, month);


--
-- Name: hire_bills hire_bills_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.hire_bills
    ADD CONSTRAINT hire_bills_pkey PRIMARY KEY (id);


--
-- Name: house_estimates house_estimates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.house_estimates
    ADD CONSTRAINT house_estimates_pkey PRIMARY KEY (id);


--
-- Name: hs_incidents hs_incidents_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.hs_incidents
    ADD CONSTRAINT hs_incidents_pkey PRIMARY KEY (id);


--
-- Name: hs_workers hs_workers_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.hs_workers
    ADD CONSTRAINT hs_workers_pkey PRIMARY KEY (id);


--
-- Name: import_map import_map_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.import_map
    ADD CONSTRAINT import_map_pkey PRIMARY KEY (origin, kind, origin_id);


--
-- Name: internal_bills internal_bills_equipment_id_project_id_month_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.internal_bills
    ADD CONSTRAINT internal_bills_equipment_id_project_id_month_key UNIQUE (equipment_id, project_id, month);


--
-- Name: internal_bills internal_bills_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.internal_bills
    ADD CONSTRAINT internal_bills_pkey PRIMARY KEY (id);


--
-- Name: inv_policy inv_policy_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.inv_policy
    ADD CONSTRAINT inv_policy_pkey PRIMARY KEY (material_id);


--
-- Name: invoice_lines invoice_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.invoice_lines
    ADD CONSTRAINT invoice_lines_pkey PRIMARY KEY (id);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);


--
-- Name: ipc_lines ipc_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ipc_lines
    ADD CONSTRAINT ipc_lines_pkey PRIMARY KEY (id);


--
-- Name: ipc ipc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ipc
    ADD CONSTRAINT ipc_pkey PRIMARY KEY (id);


--
-- Name: issue_lines issue_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.issue_lines
    ADD CONSTRAINT issue_lines_pkey PRIMARY KEY (id);


--
-- Name: issues issues_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.issues
    ADD CONSTRAINT issues_pkey PRIMARY KEY (id);


--
-- Name: kpi_snapshots kpi_snapshots_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.kpi_snapshots
    ADD CONSTRAINT kpi_snapshots_pkey PRIMARY KEY (id);


--
-- Name: kpi_snapshots kpi_snapshots_project_id_date_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.kpi_snapshots
    ADD CONSTRAINT kpi_snapshots_project_id_date_key UNIQUE (project_id, date);


--
-- Name: labour_burden labour_burden_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.labour_burden
    ADD CONSTRAINT labour_burden_pkey PRIMARY KEY (id);


--
-- Name: labour_burden labour_burden_trade_id_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.labour_burden
    ADD CONSTRAINT labour_burden_trade_id_key UNIQUE (trade_id);


--
-- Name: loans loans_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.loans
    ADD CONSTRAINT loans_pkey PRIMARY KEY (id);


--
-- Name: log_checks log_checks_book_id_date_item_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_checks
    ADD CONSTRAINT log_checks_book_id_date_item_key UNIQUE (book_id, date, item);


--
-- Name: log_checks log_checks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_checks
    ADD CONSTRAINT log_checks_pkey PRIMARY KEY (id);


--
-- Name: log_fluids log_fluids_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_fluids
    ADD CONSTRAINT log_fluids_pkey PRIMARY KEY (id);


--
-- Name: log_meters log_meters_log_id_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_meters
    ADD CONSTRAINT log_meters_log_id_code_key UNIQUE (log_id, code);


--
-- Name: log_meters log_meters_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_meters
    ADD CONSTRAINT log_meters_pkey PRIMARY KEY (id);


--
-- Name: log_service log_service_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_service
    ADD CONSTRAINT log_service_pkey PRIMARY KEY (id);


--
-- Name: log_tools log_tools_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.log_tools
    ADD CONSTRAINT log_tools_pkey PRIMARY KEY (id);


--
-- Name: logbooks logbooks_equipment_id_period_sheet_type_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.logbooks
    ADD CONSTRAINT logbooks_equipment_id_period_sheet_type_key UNIQUE (equipment_id, period, sheet_type);


--
-- Name: logbooks logbooks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.logbooks
    ADD CONSTRAINT logbooks_pkey PRIMARY KEY (id);


--
-- Name: login_attempts login_attempts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.login_attempts
    ADD CONSTRAINT login_attempts_pkey PRIMARY KEY (id);


--
-- Name: logsheets logsheets_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.logsheets
    ADD CONSTRAINT logsheets_pkey PRIMARY KEY (id);


--
-- Name: lookahead lookahead_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.lookahead
    ADD CONSTRAINT lookahead_pkey PRIMARY KEY (id);


--
-- Name: maint_plans maint_plans_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.maint_plans
    ADD CONSTRAINT maint_plans_pkey PRIMARY KEY (id);


--
-- Name: mat_causes mat_causes_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mat_causes
    ADD CONSTRAINT mat_causes_pkey PRIMARY KEY (id);


--
-- Name: material_coefficients material_coefficients_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.material_coefficients
    ADD CONSTRAINT material_coefficients_pkey PRIMARY KEY (id);


--
-- Name: materials materials_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.materials
    ADD CONSTRAINT materials_code_key UNIQUE (code);


--
-- Name: materials materials_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.materials
    ADD CONSTRAINT materials_pkey PRIMARY KEY (id);


--
-- Name: maturity_checks maturity_checks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.maturity_checks
    ADD CONSTRAINT maturity_checks_pkey PRIMARY KEY (id);


--
-- Name: maturity_checks maturity_checks_year_qkey_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.maturity_checks
    ADD CONSTRAINT maturity_checks_year_qkey_key UNIQUE (year, qkey);


--
-- Name: measurement_lines measurement_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.measurement_lines
    ADD CONSTRAINT measurement_lines_pkey PRIMARY KEY (id);


--
-- Name: measurements measurements_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.measurements
    ADD CONSTRAINT measurements_pkey PRIMARY KEY (id);


--
-- Name: mg_tags mg_tags_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mg_tags
    ADD CONSTRAINT mg_tags_pkey PRIMARY KEY (line_id);


--
-- Name: mh_meta mh_meta_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mh_meta
    ADD CONSTRAINT mh_meta_pkey PRIMARY KEY (k);


--
-- Name: mh_sheets mh_sheets_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mh_sheets
    ADD CONSTRAINT mh_sheets_pkey PRIMARY KEY (id);


--
-- Name: mix_designs mix_designs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mix_designs
    ADD CONSTRAINT mix_designs_pkey PRIMARY KEY (id);


--
-- Name: mix_lines mix_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mix_lines
    ADD CONSTRAINT mix_lines_pkey PRIMARY KEY (id);


--
-- Name: mrq_lines mrq_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mrq_lines
    ADD CONSTRAINT mrq_lines_pkey PRIMARY KEY (id);


--
-- Name: mrq mrq_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.mrq
    ADD CONSTRAINT mrq_pkey PRIMARY KEY (id);


--
-- Name: ncrs ncrs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ncrs
    ADD CONSTRAINT ncrs_pkey PRIMARY KEY (id);


--
-- Name: nfrs18_map nfrs18_map_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.nfrs18_map
    ADD CONSTRAINT nfrs18_map_pkey PRIMARY KEY (account_id);


--
-- Name: oh_budget oh_budget_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.oh_budget
    ADD CONSTRAINT oh_budget_pkey PRIMARY KEY (id);


--
-- Name: operator_violations operator_violations_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.operator_violations
    ADD CONSTRAINT operator_violations_pkey PRIMARY KEY (id);


--
-- Name: pa_formula pa_formula_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.pa_formula
    ADD CONSTRAINT pa_formula_pkey PRIMARY KEY (project_id);


--
-- Name: pa_indices pa_indices_code_period_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.pa_indices
    ADD CONSTRAINT pa_indices_code_period_key UNIQUE (code, period);


--
-- Name: pa_indices pa_indices_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.pa_indices
    ADD CONSTRAINT pa_indices_pkey PRIMARY KEY (id);


--
-- Name: parties parties_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.parties
    ADD CONSTRAINT parties_code_key UNIQUE (code);


--
-- Name: parties parties_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.parties
    ADD CONSTRAINT parties_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: plant_run_lines plant_run_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.plant_run_lines
    ADD CONSTRAINT plant_run_lines_pkey PRIMARY KEY (id);


--
-- Name: plant_runs plant_runs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.plant_runs
    ADD CONSTRAINT plant_runs_pkey PRIMARY KEY (id);


--
-- Name: plant_runs plant_runs_plant_id_date_shift_no_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.plant_runs
    ADD CONSTRAINT plant_runs_plant_id_date_shift_no_key UNIQUE (plant_id, date, shift, no);


--
-- Name: plant_tests plant_tests_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.plant_tests
    ADD CONSTRAINT plant_tests_pkey PRIMARY KEY (id);


--
-- Name: plants plants_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.plants
    ADD CONSTRAINT plants_code_key UNIQUE (code);


--
-- Name: plants plants_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.plants
    ADD CONSTRAINT plants_pkey PRIMARY KEY (id);


--
-- Name: po_lines po_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.po_lines
    ADD CONSTRAINT po_lines_pkey PRIMARY KEY (id);


--
-- Name: po po_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.po
    ADD CONSTRAINT po_pkey PRIMARY KEY (id);


--
-- Name: po_revisions po_revisions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.po_revisions
    ADD CONSTRAINT po_revisions_pkey PRIMARY KEY (id);


--
-- Name: post_queue post_queue_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.post_queue
    ADD CONSTRAINT post_queue_pkey PRIMARY KEY (voucher_id);


--
-- Name: pr_lines pr_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.pr_lines
    ADD CONSTRAINT pr_lines_pkey PRIMARY KEY (id);


--
-- Name: pr pr_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.pr
    ADD CONSTRAINT pr_pkey PRIMARY KEY (id);


--
-- Name: proc_adjust proc_adjust_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.proc_adjust
    ADD CONSTRAINT proc_adjust_pkey PRIMARY KEY (id);


--
-- Name: proc_alloc proc_alloc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.proc_alloc
    ADD CONSTRAINT proc_alloc_pkey PRIMARY KEY (id);


--
-- Name: proc_inv_alloc proc_inv_alloc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.proc_inv_alloc
    ADD CONSTRAINT proc_inv_alloc_pkey PRIMARY KEY (id);


--
-- Name: proc_pay_alloc proc_pay_alloc_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.proc_pay_alloc
    ADD CONSTRAINT proc_pay_alloc_pkey PRIMARY KEY (id);


--
-- Name: projects projects_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.projects
    ADD CONSTRAINT projects_code_key UNIQUE (code);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: prov_moves prov_moves_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.prov_moves
    ADD CONSTRAINT prov_moves_pkey PRIMARY KEY (id);


--
-- Name: provisions provisions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.provisions
    ADD CONSTRAINT provisions_pkey PRIMARY KEY (id);


--
-- Name: qa_tests qa_tests_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.qa_tests
    ADD CONSTRAINT qa_tests_pkey PRIMARY KEY (id);


--
-- Name: ra_analyses ra_analyses_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ra_analyses
    ADD CONSTRAINT ra_analyses_pkey PRIMARY KEY (id);


--
-- Name: ra_norm_lines ra_norm_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ra_norm_lines
    ADD CONSTRAINT ra_norm_lines_pkey PRIMARY KEY (id);


--
-- Name: ra_norms ra_norms_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ra_norms
    ADD CONSTRAINT ra_norms_code_key UNIQUE (code);


--
-- Name: ra_norms ra_norms_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ra_norms
    ADD CONSTRAINT ra_norms_pkey PRIMARY KEY (id);


--
-- Name: ra_seed_log ra_seed_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ra_seed_log
    ADD CONSTRAINT ra_seed_log_pkey PRIMARY KEY (tag);


--
-- Name: rate_analysis rate_analysis_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.rate_analysis
    ADD CONSTRAINT rate_analysis_pkey PRIMARY KEY (id);


--
-- Name: rate_books rate_books_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.rate_books
    ADD CONSTRAINT rate_books_code_key UNIQUE (code);


--
-- Name: rate_books rate_books_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.rate_books
    ADD CONSTRAINT rate_books_pkey PRIMARY KEY (id);


--
-- Name: rent_deductions rent_deductions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.rent_deductions
    ADD CONSTRAINT rent_deductions_pkey PRIMARY KEY (id);


--
-- Name: res_pool res_pool_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.res_pool
    ADD CONSTRAINT res_pool_code_key UNIQUE (code);


--
-- Name: res_pool res_pool_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.res_pool
    ADD CONSTRAINT res_pool_pkey PRIMARY KEY (id);


--
-- Name: res_rates res_rates_book_id_res_id_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.res_rates
    ADD CONSTRAINT res_rates_book_id_res_id_key UNIQUE (book_id, res_id);


--
-- Name: res_rates res_rates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.res_rates
    ADD CONSTRAINT res_rates_pkey PRIMARY KEY (id);


--
-- Name: return_lines return_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.return_lines
    ADD CONSTRAINT return_lines_pkey PRIMARY KEY (id);


--
-- Name: returns returns_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.returns
    ADD CONSTRAINT returns_pkey PRIMARY KEY (id);


--
-- Name: risks risks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.risks
    ADD CONSTRAINT risks_pkey PRIMARY KEY (id);


--
-- Name: sa_moves sa_moves_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sa_moves
    ADD CONSTRAINT sa_moves_pkey PRIMARY KEY (id);


--
-- Name: sa_pools sa_pools_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sa_pools
    ADD CONSTRAINT sa_pools_pkey PRIMARY KEY (id);


--
-- Name: sa_runs sa_runs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sa_runs
    ADD CONSTRAINT sa_runs_pkey PRIMARY KEY (id);


--
-- Name: safety_checks safety_checks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.safety_checks
    ADD CONSTRAINT safety_checks_pkey PRIMARY KEY (id);


--
-- Name: sc_bill_items sc_bill_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_bill_items
    ADD CONSTRAINT sc_bill_items_pkey PRIMARY KEY (id);


--
-- Name: sc_bill_recoveries sc_bill_recoveries_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_bill_recoveries
    ADD CONSTRAINT sc_bill_recoveries_pkey PRIMARY KEY (id);


--
-- Name: sc_bills sc_bills_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_bills
    ADD CONSTRAINT sc_bills_pkey PRIMARY KEY (id);


--
-- Name: sc_moves sc_moves_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_moves
    ADD CONSTRAINT sc_moves_pkey PRIMARY KEY (id);


--
-- Name: sc_order_items sc_order_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_order_items
    ADD CONSTRAINT sc_order_items_pkey PRIMARY KEY (id);


--
-- Name: sc_order_mats sc_order_mats_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_order_mats
    ADD CONSTRAINT sc_order_mats_pkey PRIMARY KEY (id);


--
-- Name: sc_orders sc_orders_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sc_orders
    ADD CONSTRAINT sc_orders_pkey PRIMARY KEY (id);


--
-- Name: sched_baseline_acts sched_baseline_acts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sched_baseline_acts
    ADD CONSTRAINT sched_baseline_acts_pkey PRIMARY KEY (id);


--
-- Name: sched_baselines sched_baselines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sched_baselines
    ADD CONSTRAINT sched_baselines_pkey PRIMARY KEY (id);


--
-- Name: sched_calendars sched_calendars_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sched_calendars
    ADD CONSTRAINT sched_calendars_pkey PRIMARY KEY (id);


--
-- Name: sched_holidays sched_holidays_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sched_holidays
    ADD CONSTRAINT sched_holidays_pkey PRIMARY KEY (id);


--
-- Name: sched_runs sched_runs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sched_runs
    ADD CONSTRAINT sched_runs_pkey PRIMARY KEY (id);


--
-- Name: sched_windows sched_windows_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sched_windows
    ADD CONSTRAINT sched_windows_pkey PRIMARY KEY (id);


--
-- Name: sequences sequences_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sequences
    ADD CONSTRAINT sequences_pkey PRIMARY KEY (doc_type, fy);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (token);


--
-- Name: settings settings_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (key);


--
-- Name: site_mode_cfg site_mode_cfg_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.site_mode_cfg
    ADD CONSTRAINT site_mode_cfg_pkey PRIMARY KEY (scope);


--
-- Name: site_packs site_packs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.site_packs
    ADD CONSTRAINT site_packs_pkey PRIMARY KEY (id);


--
-- Name: staff staff_code_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.staff
    ADD CONSTRAINT staff_code_key UNIQUE (code);


--
-- Name: staff staff_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.staff
    ADD CONSTRAINT staff_pkey PRIMARY KEY (id);


--
-- Name: stock_balances stock_balances_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.stock_balances
    ADD CONSTRAINT stock_balances_pkey PRIMARY KEY (project_id, store_id, material_id);


--
-- Name: stock_counts stock_counts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.stock_counts
    ADD CONSTRAINT stock_counts_pkey PRIMARY KEY (id);


--
-- Name: stock_ledger stock_ledger_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.stock_ledger
    ADD CONSTRAINT stock_ledger_pkey PRIMARY KEY (id);


--
-- Name: stores stores_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.stores
    ADD CONSTRAINT stores_pkey PRIMARY KEY (id);


--
-- Name: submittals submittals_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.submittals
    ADD CONSTRAINT submittals_pkey PRIMARY KEY (id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: tds_rates_fy tds_rates_fy_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.tds_rates_fy
    ADD CONSTRAINT tds_rates_fy_pkey PRIMARY KEY (id);


--
-- Name: tds_rates tds_rates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.tds_rates
    ADD CONSTRAINT tds_rates_pkey PRIMARY KEY (id);


--
-- Name: trade_moves trade_moves_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.trade_moves
    ADD CONSTRAINT trade_moves_pkey PRIMARY KEY (id);


--
-- Name: trades trades_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.trades
    ADD CONSTRAINT trades_pkey PRIMARY KEY (id);


--
-- Name: transfer_lines transfer_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.transfer_lines
    ADD CONSTRAINT transfer_lines_pkey PRIMARY KEY (id);


--
-- Name: transfers transfers_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.transfers
    ADD CONSTRAINT transfers_pkey PRIMARY KEY (id);


--
-- Name: udpr_fronts udpr_fronts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_fronts
    ADD CONSTRAINT udpr_fronts_pkey PRIMARY KEY (id);


--
-- Name: udpr_head udpr_head_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_head
    ADD CONSTRAINT udpr_head_pkey PRIMARY KEY (dpr_id);


--
-- Name: udpr_issue_days udpr_issue_days_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_issue_days
    ADD CONSTRAINT udpr_issue_days_pkey PRIMARY KEY (issue_id, dpr_id);


--
-- Name: udpr_issue_x udpr_issue_x_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_issue_x
    ADD CONSTRAINT udpr_issue_x_pkey PRIMARY KEY (issue_id);


--
-- Name: udpr_layouts udpr_layouts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_layouts
    ADD CONSTRAINT udpr_layouts_pkey PRIMARY KEY (id);


--
-- Name: udpr_log udpr_log_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_log
    ADD CONSTRAINT udpr_log_pkey PRIMARY KEY (id);


--
-- Name: udpr_lx udpr_lx_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_lx
    ADD CONSTRAINT udpr_lx_pkey PRIMARY KEY (part, line_id);


--
-- Name: udpr_project udpr_project_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_project
    ADD CONSTRAINT udpr_project_pkey PRIMARY KEY (project_id);


--
-- Name: udpr_revisions udpr_revisions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_revisions
    ADD CONSTRAINT udpr_revisions_pkey PRIMARY KEY (id);


--
-- Name: udpr_rows udpr_rows_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_rows
    ADD CONSTRAINT udpr_rows_pkey PRIMARY KEY (id);


--
-- Name: udpr_templates udpr_templates_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_templates
    ADD CONSTRAINT udpr_templates_pkey PRIMARY KEY (id);


--
-- Name: udpr_tpl_versions udpr_tpl_versions_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_tpl_versions
    ADD CONSTRAINT udpr_tpl_versions_pkey PRIMARY KEY (id);


--
-- Name: udpr_values udpr_values_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_values
    ADD CONSTRAINT udpr_values_pkey PRIMARY KEY (dpr_id, key);


--
-- Name: udpr_work udpr_work_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.udpr_work
    ADD CONSTRAINT udpr_work_pkey PRIMARY KEY (work_id);


--
-- Name: user_shortcuts user_shortcuts_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.user_shortcuts
    ADD CONSTRAINT user_shortcuts_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: variations variations_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.variations
    ADD CONSTRAINT variations_pkey PRIMARY KEY (id);


--
-- Name: vendor_ratings vendor_ratings_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.vendor_ratings
    ADD CONSTRAINT vendor_ratings_pkey PRIMARY KEY (id);


--
-- Name: verify_items verify_items_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.verify_items
    ADD CONSTRAINT verify_items_pkey PRIMARY KEY (id);


--
-- Name: verify_items verify_items_round_id_kind_ref_id_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.verify_items
    ADD CONSTRAINT verify_items_round_id_kind_ref_id_key UNIQUE (round_id, kind, ref_id);


--
-- Name: verify_rounds verify_rounds_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.verify_rounds
    ADD CONSTRAINT verify_rounds_pkey PRIMARY KEY (id);


--
-- Name: voucher_lines voucher_lines_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.voucher_lines
    ADD CONSTRAINT voucher_lines_pkey PRIMARY KEY (id);


--
-- Name: vouchers vouchers_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.vouchers
    ADD CONSTRAINT vouchers_pkey PRIMARY KEY (id);


--
-- Name: wbs wbs_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.wbs
    ADD CONSTRAINT wbs_pkey PRIMARY KEY (id);


--
-- Name: web_kv web_kv_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.web_kv
    ADD CONSTRAINT web_kv_pkey PRIMARY KEY (name);


--
-- Name: work_orders work_orders_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.work_orders
    ADD CONSTRAINT work_orders_pkey PRIMARY KEY (id);


--
-- Name: ws_roles ws_roles_key_key; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ws_roles
    ADD CONSTRAINT ws_roles_key_key UNIQUE (key);


--
-- Name: ws_roles ws_roles_pkey; Type: CONSTRAINT; Schema: buildcore; Owner: -
--

ALTER TABLE ONLY buildcore.ws_roles
    ADD CONSTRAINT ws_roles_pkey PRIMARY KEY (id);


--
-- Name: ix_activity_ts; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_activity_ts ON buildcore.activity USING btree (id DESC);


--
-- Name: ix_actres; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_actres ON buildcore.act_resources USING btree (project_id, activity_id);


--
-- Name: ix_ai_items_doc; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_ai_items_doc ON buildcore.ai_items USING btree (doc_id);


--
-- Name: ix_bla; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_bla ON buildcore.sched_baseline_acts USING btree (baseline_id);


--
-- Name: ix_book_eq; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_book_eq ON buildcore.logbooks USING btree (equipment_id, period);


--
-- Name: ix_cal; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_cal ON buildcore.ca_letters USING btree (project_id, direction, status);


--
-- Name: ix_catb; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_catb ON buildcore.ca_timebars USING btree (project_id, status);


--
-- Name: ix_citem; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_citem ON buildcore.contract_items USING btree (contract_id);


--
-- Name: ix_cla_c; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_cla_c ON buildcore.cl_alloc USING btree (cost_code_id);


--
-- Name: ix_clbl; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_clbl ON buildcore.cl_budget_lines USING btree (version_id, cost_code_id);


--
-- Name: ix_clbv; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_clbv ON buildcore.cl_budget_versions USING btree (project_id, kind);


--
-- Name: ix_clc_b; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_clc_b ON buildcore.cl_codes USING btree (boq_item_id);


--
-- Name: ix_clc_p; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_clc_p ON buildcore.cl_codes USING btree (project_id, kind);


--
-- Name: ix_clca; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_clca ON buildcore.cl_close_accruals USING btree (close_id);


--
-- Name: ix_clg; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_clg ON buildcore.cl_gang_hours USING btree (dpr_labour_id);


--
-- Name: ix_cmn; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_cmn ON buildcore.cm_notes USING btree (user_id, read_at);


--
-- Name: ix_cmp; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_cmp ON buildcore.cm_posts USING btree (thread_id);


--
-- Name: ix_cmt; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_cmt ON buildcore.cm_threads USING btree (project_id, last_ts);


--
-- Name: ix_dmd; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_dmd ON buildcore.dm_docs USING btree (project_id, folder_id);


--
-- Name: ix_dmr; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_dmr ON buildcore.dm_revs USING btree (doc_id);


--
-- Name: ix_dmrv; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_dmrv ON buildcore.dm_reviews USING btree (reviewer_id, status);


--
-- Name: ix_dpr_survey; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_dpr_survey ON buildcore.dpr_survey USING btree (dpr_id);


--
-- Name: ix_ep_p; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_ep_p ON buildcore.exec_plan USING btree (project_id);


--
-- Name: ix_faalloc; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_faalloc ON buildcore.fa_alloc USING btree (fa_id, month);


--
-- Name: ix_facomp; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_facomp ON buildcore.fa_components USING btree (fa_id);


--
-- Name: ix_facost; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_facost ON buildcore.fa_costs USING btree (fa_id, date);


--
-- Name: ix_fcc_alert_log; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcc_alert_log ON buildcore.fcc_alert_log USING btree (alert_id);


--
-- Name: ix_fcc_alerts_owner; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcc_alerts_owner ON buildcore.fcc_alerts USING btree (owner_id);


--
-- Name: ix_fcc_alerts_project; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcc_alerts_project ON buildcore.fcc_alerts USING btree (project_id);


--
-- Name: ix_fcc_alerts_status; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcc_alerts_status ON buildcore.fcc_alerts USING btree (status, severity);


--
-- Name: ix_fcf; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcf ON buildcore.fc_follow USING btree (ref_type, ref_id);


--
-- Name: ix_fcil; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcil ON buildcore.fc_ipc_log USING btree (ipc_id);


--
-- Name: ix_fcpr; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcpr ON buildcore.fc_payreq USING btree (stage);


--
-- Name: ix_fcpr_i; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcpr_i ON buildcore.fc_payreq USING btree (invoice_id);


--
-- Name: ix_fcprl; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fcprl ON buildcore.fc_payreq_log USING btree (req_id);


--
-- Name: ix_fdr; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fdr ON buildcore.fld_drawings USING btree (project_id, number);


--
-- Name: ix_files_entity; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_files_entity ON buildcore.files USING btree (entity, entity_id);


--
-- Name: ix_fis; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fis ON buildcore.fld_issues USING btree (project_id, status);


--
-- Name: ix_frf; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_frf ON buildcore.fld_rfis USING btree (project_id, status);


--
-- Name: ix_fy_bal; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_fy_bal ON buildcore.fy_balances USING btree (fy);


--
-- Name: ix_hsi; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_hsi ON buildcore.hs_incidents USING btree (project_id, date);


--
-- Name: ix_hsw; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_hsw ON buildcore.hs_workers USING btree (project_id, party_id);


--
-- Name: ix_la; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_la ON buildcore.lookahead USING btree (project_id, week_start);


--
-- Name: ix_links_p; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_links_p ON buildcore.act_links USING btree (project_id);


--
-- Name: ix_log_tools; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_log_tools ON buildcore.log_tools USING btree (log_id);


--
-- Name: ix_logcheck; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_logcheck ON buildcore.log_checks USING btree (book_id, date);


--
-- Name: ix_logfluid; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_logfluid ON buildcore.log_fluids USING btree (book_id);


--
-- Name: ix_login_user; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_login_user ON buildcore.login_attempts USING btree (username, id DESC);


--
-- Name: ix_logmeter; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_logmeter ON buildcore.log_meters USING btree (book_id, code);


--
-- Name: ix_logservice; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_logservice ON buildcore.log_service USING btree (book_id);


--
-- Name: ix_mgt_m; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_mgt_m ON buildcore.mg_tags USING btree (mode);


--
-- Name: ix_mgt_v; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_mgt_v ON buildcore.mg_tags USING btree (voucher_id);


--
-- Name: ix_ohb; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_ohb ON buildcore.oh_budget USING btree (fy, category);


--
-- Name: ix_pa_grn; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_pa_grn ON buildcore.proc_alloc USING btree (grn_id);


--
-- Name: ix_pa_line; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_pa_line ON buildcore.proc_alloc USING btree (grn_line_id, status);


--
-- Name: ix_pia_inv; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_pia_inv ON buildcore.proc_inv_alloc USING btree (invoice_id, status);


--
-- Name: ix_pia_line; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_pia_line ON buildcore.proc_inv_alloc USING btree (grn_line_id, status);


--
-- Name: ix_ppa_inv; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_ppa_inv ON buildcore.proc_pay_alloc USING btree (invoice_id, active);


--
-- Name: ix_ppa_pay; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_ppa_pay ON buildcore.proc_pay_alloc USING btree (payment_id);


--
-- Name: ix_pq_stage; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_pq_stage ON buildcore.post_queue USING btree (stage);


--
-- Name: ix_ranl; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_ranl ON buildcore.ra_norm_lines USING btree (norm_id);


--
-- Name: ix_rd_ag; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_rd_ag ON buildcore.rent_deductions USING btree (agreement_id, status);


--
-- Name: ix_respool; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_respool ON buildcore.res_pool USING btree (type, category);


--
-- Name: ix_risks; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_risks ON buildcore.risks USING btree (project_id, status);


--
-- Name: ix_scm_o; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_scm_o ON buildcore.sc_moves USING btree (order_id, status);


--
-- Name: ix_sl_doc; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_sl_doc ON buildcore.stock_ledger USING btree (doc_type, doc_id);


--
-- Name: ix_sl_item; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_sl_item ON buildcore.stock_ledger USING btree (project_id, material_id, store_id, date);


--
-- Name: ix_tm_inv; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_tm_inv ON buildcore.trade_moves USING btree (invoice_id);


--
-- Name: ix_udf_p; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udf_p ON buildcore.udpr_fronts USING btree (project_id, kind);


--
-- Name: ix_udh_tok; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udh_tok ON buildcore.udpr_head USING btree (client_token);


--
-- Name: ix_udid; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udid ON buildcore.udpr_issue_days USING btree (dpr_id);


--
-- Name: ix_udl_d; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udl_d ON buildcore.udpr_lx USING btree (dpr_id);


--
-- Name: ix_udlog; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udlog ON buildcore.udpr_log USING btree (dpr_id);


--
-- Name: ix_udr; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udr ON buildcore.udpr_rows USING btree (dpr_id, section);


--
-- Name: ix_udr_s; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udr_s ON buildcore.udpr_rows USING btree (section);


--
-- Name: ix_udrev; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udrev ON buildcore.udpr_revisions USING btree (dpr_id);


--
-- Name: ix_udtv; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udtv ON buildcore.udpr_tpl_versions USING btree (template_id, version_no);


--
-- Name: ix_udw_d; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_udw_d ON buildcore.udpr_work USING btree (dpr_id);


--
-- Name: ix_v_date; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_v_date ON buildcore.vouchers USING btree (date);


--
-- Name: ix_v_source; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_v_source ON buildcore.vouchers USING btree (source, source_id);


--
-- Name: ix_vl_acc; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_vl_acc ON buildcore.voucher_lines USING btree (account_id);


--
-- Name: ix_vl_eq; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_vl_eq ON buildcore.voucher_lines USING btree (equipment_id);


--
-- Name: ix_vl_v; Type: INDEX; Schema: buildcore; Owner: -
--

CREATE INDEX ix_vl_v ON buildcore.voucher_lines USING btree (voucher_id);


--
-- Name: voucher_lines bco_vline_no_delete; Type: TRIGGER; Schema: buildcore; Owner: -
--

CREATE TRIGGER bco_vline_no_delete BEFORE DELETE ON buildcore.voucher_lines FOR EACH ROW EXECUTE FUNCTION buildcore.trg_bco_vline_no_delete();


--
-- Name: voucher_lines bco_vline_no_edit; Type: TRIGGER; Schema: buildcore; Owner: -
--

CREATE TRIGGER bco_vline_no_edit BEFORE UPDATE OF voucher_id, account_id, debit, credit ON buildcore.voucher_lines FOR EACH ROW EXECUTE FUNCTION buildcore.trg_bco_vline_no_edit();


--
-- Name: vouchers bco_voucher_no_delete; Type: TRIGGER; Schema: buildcore; Owner: -
--

CREATE TRIGGER bco_voucher_no_delete BEFORE DELETE ON buildcore.vouchers FOR EACH ROW EXECUTE FUNCTION buildcore.trg_bco_voucher_no_delete();


--
-- Name: vouchers bco_voucher_no_edit; Type: TRIGGER; Schema: buildcore; Owner: -
--

CREATE TRIGGER bco_voucher_no_edit BEFORE UPDATE ON buildcore.vouchers FOR EACH ROW EXECUTE FUNCTION buildcore.trg_bco_voucher_no_edit();


--
-- PostgreSQL database dump complete
--



-- keep both schemas away from Supabase's public API keys
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON SCHEMA buildcore, bcfn FROM anon;
    REVOKE ALL ON ALL TABLES IN SCHEMA buildcore FROM anon;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    REVOKE ALL ON SCHEMA buildcore, bcfn FROM authenticated;
    REVOKE ALL ON ALL TABLES IN SCHEMA buildcore FROM authenticated;
  END IF;
END $$;
