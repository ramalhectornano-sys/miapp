#!/usr/bin/env python3
"""Build an offline, deterministic installer for a NEW Supabase project.

The migration files remain the source of truth. This command neither connects to
PostgreSQL nor applies SQL. Existing projects must apply pending migrations only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_NAME = re.compile(r"(?P<version>[0-9]{12})_[a-z0-9_]+\.sql\Z")
IDENTIFIER = r"[a-z_][a-z0-9_]*"


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str
    sha256: str


def load_migrations(directory: Path) -> tuple[Migration, ...]:
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise ValueError("No hay migraciones SQL en el directorio indicado.")
    versions: set[str] = set()
    migrations: list[Migration] = []
    for path in files:
        match = MIGRATION_NAME.fullmatch(path.name)
        if not match or match["version"] in versions:
            raise ValueError("Las migraciones necesitan nombres válidos y versiones únicas.")
        versions.add(match["version"])
        raw = path.read_bytes()
        sql = raw.decode("utf-8")
        if not sql.strip() or sql.startswith("\ufeff"):
            raise ValueError("Las migraciones deben ser SQL UTF-8 sin BOM y no estar vacías.")
        migrations.append(Migration(path.name, sql, hashlib.sha256(raw).hexdigest()))
    return tuple(migrations)


def created_objects(migrations: tuple[Migration, ...], object_type: str) -> tuple[str, ...]:
    """Collect the unquoted qualified identifiers used by these migrations.

    This extracts guard names, not SQL semantics; the original SQL is preserved.
    """
    expression = re.compile(
        rf"^\s*create\s+(?:or\s+replace\s+)?{object_type}\s+"
        rf"(?:if\s+not\s+exists\s+)?((?:public|private)\.{IDENTIFIER})\b",
        re.IGNORECASE | re.MULTILINE,
    )
    return tuple(sorted({name.lower() for migration in migrations for name in expression.findall(migration.sql)}))


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_array(values: tuple[str, ...]) -> str:
    return "array[" + ",".join(sql_literal(value) for value in values) + "]::text[]"


def render_guard(migrations: tuple[Migration, ...]) -> str:
    tables = created_objects(migrations, "table")
    functions = created_objects(migrations, "function")
    if not {"public.profiles", "public.applications", "private.oauth_states"}.issubset(tables):
        raise ValueError("Faltan tablas esenciales de Trabajo YA; no se genera un instalador incompleto.")
    return f"""-- La comprobación ocurre antes de crear o modificar cualquier objeto.
-- Auth y Storage estándar deben existir; sus tablas vacías son compatibles.
do $trabajoya_new_project_guard$
declare
  existing_objects text[];
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('trabajo-ya:install-new-project', 0)
  );
  if pg_catalog.to_regclass('auth.users') is null
     or pg_catalog.to_regclass('storage.buckets') is null
     or pg_catalog.to_regclass('storage.objects') is null then
    raise exception 'Trabajo YA: este archivo requiere un proyecto Supabase nuevo con Auth y Storage habilitados.';
  end if;

  select pg_catalog.array_agg(object_name order by object_name) into existing_objects
    from pg_catalog.unnest({sql_array(tables)}) as objects(object_name)
    where pg_catalog.to_regclass(object_name) is not null;
  if existing_objects is not null then
    raise exception 'Trabajo YA: ya existen tablas u objetos de la aplicación (%). No se cambió nada. Aplicá solo las migraciones pendientes; este instalador es para un proyecto nuevo.',
      pg_catalog.array_to_string(existing_objects, ', ');
  end if;

  select pg_catalog.array_agg(distinct n.nspname || '.' || p.proname) into existing_objects
    from pg_catalog.pg_proc as p
    join pg_catalog.pg_namespace as n on n.oid = p.pronamespace
    where n.nspname || '.' || p.proname = any({sql_array(functions)});
  if existing_objects is not null then
    raise exception 'Trabajo YA: ya existen funciones de la aplicación. No se cambió nada. Aplicá solo las migraciones pendientes en ese proyecto.';
  end if;

  if exists (
    select 1 from pg_catalog.pg_trigger as t
    join pg_catalog.pg_class as c on c.oid = t.tgrelid
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where not t.tgisinternal and (
      (n.nspname = 'auth' and c.relname = 'users' and t.tgname = 'autoempleo_new_user')
      or (n.nspname = 'storage' and c.relname = 'objects' and t.tgname = 'protect_delivered_resume_object')
    )
  ) or exists (
    select 1 from pg_catalog.pg_policy as p
    join pg_catalog.pg_class as c on c.oid = p.polrelid
    join pg_catalog.pg_namespace as n on n.oid = c.relnamespace
    where n.nspname = 'storage' and c.relname = 'objects'
      and p.polname in ('autoempleo_private_objects_read', 'autoempleo_private_objects_insert', 'autoempleo_private_objects_delete')
  ) then
    raise exception 'Trabajo YA: ya existen permisos o triggers de la aplicación. No se cambió nada. Aplicá solo las migraciones pendientes.';
  end if;

  if exists (select 1 from storage.buckets where id in ('resumes', 'profile-photos')) then
    raise exception 'Trabajo YA: ya existen buckets resumes o profile-photos. No se cambió nada. Usá un proyecto nuevo dedicado o revisá las migraciones pendientes.';
  end if;
  if exists (select 1 from auth.users limit 1) then
    raise exception 'Trabajo YA: este proyecto ya tiene usuarios de la aplicación. No se cambió nada. Usá un proyecto nuevo o revisá las migraciones pendientes antes de continuar.';
  end if;
end;
$trabajoya_new_project_guard$;
"""


def render_bundle(migrations: tuple[Migration, ...]) -> str:
    fingerprint = hashlib.sha256()
    for migration in migrations:
        fingerprint.update(migration.name.encode("utf-8") + b"\0" + migration.sql.encode("utf-8") + b"\0")
    header = [
        "-- Trabajo YA: instalación ÚNICAMENTE en un proyecto Supabase NUEVO y vacío.",
        "-- Generado por: python scripts/build_database_install.py",
        "-- No editar: las fuentes son supabase/migrations/*.sql.",
        "-- Ejecutar el archivo COMPLETO una sola vez en SQL Editor, con rol postgres.",
        "-- No ejecutar sobre una instalación existente ni combinar con supabase db push.",
        "-- No contiene usuarios de prueba, semillas ni credenciales privadas.",
        f"-- Cantidad de migraciones: {len(migrations)}",
        f"-- SHA-256 del conjunto (nombre + NUL + SQL + NUL): {fingerprint.hexdigest()}",
        "-- Manifiesto SHA-256 de los archivos originales, en orden de aplicación:",
    ]
    header.extend(f"-- {migration.name}  {migration.sha256}" for migration in migrations)
    sections = ["\n".join(header) + "\n\nBEGIN;\n\n", render_guard(migrations)]
    for migration in migrations:
        sections.append(f"\n-- ===== INICIO MIGRACIÓN: {migration.name} =====\n")
        sections.append(migration.sql)
        if not migration.sql.endswith("\n"):
            sections.append("\n")
        sections.append(f"-- ===== FIN MIGRACIÓN: {migration.name} =====\n")
    sections.append("\n-- Commit confirma únicamente el esquema; no verifica IA, Gmail ni tareas.\nCOMMIT;\n")
    return "".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generar SQL para instalar Trabajo YA en Supabase nuevo, sin conectarse a la base.")
    parser.add_argument("--migrations-dir", type=Path, default=PROJECT_ROOT / "supabase/migrations")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "supabase/install-new-project.sql")
    parser.add_argument("--check", action="store_true", help="Comprobar que el archivo generado está actualizado, sin escribir.")
    args = parser.parse_args(argv)
    try:
        migrations = load_migrations(args.migrations_dir)
        expected = render_bundle(migrations)
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != expected.encode("utf-8"):
                print("El instalador SQL falta o está desactualizado. Ejecutá python scripts/build_database_install.py.", file=sys.stderr)
                return 1
            print("Instalador SQL actualizado. No se conectó ni se aplicó a ninguna base de datos.")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(expected.encode("utf-8"))
        print(f"Instalador SQL generado con {len(migrations)} migraciones. No se aplicó a ninguna base de datos.")
        return 0
    except (OSError, UnicodeError, ValueError):
        print("No se pudo generar el instalador: revisá el directorio, los nombres y la codificación de las migraciones.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
