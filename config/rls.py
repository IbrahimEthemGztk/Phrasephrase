"""Supabase'de `public` şemasındaki tablolar REST API'ye (PostgREST) açıktır.

Uygulama bu API'yi kullanmaz; Django `postgres` rolüyle bağlanır ve RLS'i atlar. Bu yüzden
her yeni tabloda RLS açılıp hiçbir ilke tanımlanmaz: API üzerinden erişim tamamen kapanır.
Migration'larda `enable_rls('app_model', ...)` operasyonuyla kullanılır. PostgreSQL dışındaki
veritabanlarında (yerel SQLite) hiçbir şey yapmaz.
"""

from django.db import migrations


def enable_rls(*tables):
    def forwards(apps, schema_editor):
        if schema_editor.connection.vendor != 'postgresql':
            return
        for table in tables:
            schema_editor.execute(f'ALTER TABLE {schema_editor.quote_name(table)} ENABLE ROW LEVEL SECURITY')

    def backwards(apps, schema_editor):
        if schema_editor.connection.vendor != 'postgresql':
            return
        for table in tables:
            schema_editor.execute(f'ALTER TABLE {schema_editor.quote_name(table)} DISABLE ROW LEVEL SECURITY')

    return migrations.RunPython(forwards, backwards)
