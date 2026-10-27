from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from gestor_biologica_monco.models import (
    Bovino,
    ControlPeso,
    DiagnosticoGestacion,
    Inseminacion,
    Lote,
    Madre,
    Parcela,
    Parto,
    PajuelaSemen,
    Predio,
    Raza,
)


class Command(BaseCommand):
    help = "Carga registros de demostración sin modificar los datos existentes."

    def handle(self, *_args, **_options):
        del _args, _options
        today = timezone.localdate()
        angus, _ = Raza.objects.get_or_create(
            nombre_raza="Angus",
            defaults={"origen": "Escocia"},
        )
        hereford, _ = Raza.objects.get_or_create(
            nombre_raza="Hereford",
            defaults={"origen": "Inglaterra"},
        )
        predio, _ = Predio.objects.get_or_create(
            nombre="Predio de demostración",
            defaults={"ubicacion": "Moncopulli"},
        )
        parcela, _ = Parcela.objects.get_or_create(
            predio=predio,
            codigo="DEMO-PARC-01",
        )
        Lote.objects.get_or_create(
            parcela=parcela,
            nombre_lote="Maternidad",
            defaults={"descripcion": "Lote de demostración para maternidad y crías."},
        )

        madre, _ = Madre.objects.get_or_create(
            sexo="Hembra",
            fecha_nacimiento=date(2019, 3, 12),
            estado_actual="Reproductora",
        )
        toro, _ = Bovino.objects.get_or_create(
            codigo_rfid="DEMO-MONCO-TORO-001",
            defaults={
                "sexo": "Macho",
                "fecha_nacimiento": date(2020, 5, 8),
                "raza": angus,
                "estado_actual": "Activo",
            },
        )
        vaca, _ = Bovino.objects.get_or_create(
            codigo_rfid="DEMO-MONCO-VACA-001",
            defaults={
                "sexo": "Hembra",
                "fecha_nacimiento": date(2021, 2, 14),
                "raza": angus,
                "madre": madre,
                "estado_actual": "Reproductora",
            },
        )
        vaca_reciente, _ = Bovino.objects.get_or_create(
            codigo_rfid="DEMO-MONCO-VACA-002",
            defaults={
                "sexo": "Hembra",
                "fecha_nacimiento": date(2022, 7, 3),
                "raza": hereford,
                "estado_actual": "Activa",
            },
        )
        cria_madre, _ = Madre.objects.get_or_create(
            sexo="Hembra",
            fecha_nacimiento=date(2021, 2, 14),
            estado_actual="Reproductora",
        )
        cria_fecha = today - timedelta(days=7)
        cria, _ = Bovino.objects.get_or_create(
            codigo_rfid="DEMO-MONCO-CRIA-001",
            defaults={
                "sexo": "Hembra",
                "fecha_nacimiento": cria_fecha,
                "raza": angus,
                "madre": cria_madre,
                "estado_actual": "Cría",
            },
        )

        pajuela, _ = PajuelaSemen.objects.get_or_create(
            lote_pajuela="DEMO-PAJ-001",
            defaults={
                "toro": toro,
                "fecha_extraccion": today - timedelta(days=365),
                "stock": 20,
            },
        )
        servicio_fecha = cria.fecha_nacimiento - timedelta(days=283)
        servicio, _ = Inseminacion.objects.get_or_create(
            vaca=vaca,
            pajuela=pajuela,
            defaults={
                "fecha_servicio": timezone.make_aware(
                    datetime.combine(servicio_fecha, time(hour=8))
                )
            },
        )
        diagnostico, _ = DiagnosticoGestacion.objects.get_or_create(
            inseminacion=servicio,
            defaults={
                "resultado": DiagnosticoGestacion.RESULTADO_CHOICES[0][0],
                "semanas": 8,
                "fecha_diagnostico": servicio_fecha + timedelta(days=56),
            },
        )
        Parto.objects.get_or_create(
            diagnostico=diagnostico,
            defaults={
                "cria": cria,
                "fecha_parto": cria_fecha,
                "tipo_parto": "Natural",
                "observaciones": "Parto de demostración sin complicaciones.",
            },
        )

        servicio_reciente = timezone.make_aware(
            datetime.combine(today.replace(day=1), time(hour=9))
        )
        Inseminacion.objects.get_or_create(
            vaca=vaca_reciente,
            pajuela=pajuela,
            defaults={"fecha_servicio": servicio_reciente},
        )
        ControlPeso.objects.get_or_create(
            bovino=cria,
            fecha_pesaje=cria.fecha_nacimiento,
            defaults={"peso_kg": 42.5},
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Datos de demostración listos: 4 bovinos, 2 inseminaciones, "
                "1 diagnóstico, 1 parto y 1 control de peso."
            )
        )
