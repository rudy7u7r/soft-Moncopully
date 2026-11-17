#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def inicializar_base_datos_automatica():
    """
    Ejecuta automáticamente las migraciones de la base de datos SQLite y la carga
    inicial de datos cuando el proyecto se clona y se inicia en otro computador.
    """
    try:
        import django
        from django.core.management import call_command
        django.setup()
        call_command('migrate', interactive=False, verbosity=1)
        from gestor_biologica_monco.rbac import asegurar_usuarios_iniciales
        from gestor_biologica_monco.models import Bovino
        asegurar_usuarios_iniciales()
        if Bovino.objects.count() < 100:
            call_command('cargar_datos_demo')
    except Exception as exc:
        print(f"Aviso de inicialización automática: {exc}")


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Si se ejecuta 'runserver', aplicar migraciones y datos iniciales automáticamente
    if len(sys.argv) >= 2 and sys.argv[1] == 'runserver':
        if os.environ.get('RUN_MAIN') == 'true' or '--noreload' in sys.argv:
            inicializar_base_datos_automatica()

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
