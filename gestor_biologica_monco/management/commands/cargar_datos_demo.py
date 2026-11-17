import random
from datetime import date, datetime, time, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from gestor_biologica_monco.models import (
    Bovino,
    DiagnosticoGestacion,
    Inseminacion,
    Madre,
    Parentesco,
    Parto,
    PajuelaSemen,
    Raza,
)


class Command(BaseCommand):
    help = "Genera más de 1.500 vacas aleatorias, 60 toros y 105 lotes de pajuelas con inseminaciones, diagnósticos y partos."

    def handle(self, *_args, **_options):
        del _args, _options
        random.seed(2026)
        today = timezone.localdate()

        razas_info = [
            ("Angus", "Escocia"),
            ("Hereford", "Inglaterra"),
            ("Holstein Friesian", "Países Bajos"),
            ("Overo Colorado", "Alemania / Chile"),
            ("Simmental", "Suiza"),
            ("Jersey", "Reino Unido"),
            ("Charolais", "Francia"),
        ]
        razas_objs = []
        for nombre, origen in razas_info:
            r_obj, _ = Raza.objects.get_or_create(nombre_raza=nombre, defaults={"origen": origen})
            razas_objs.append(r_obj)

        rfids_existentes = set(Bovino.objects.values_list("codigo_rfid", flat=True))
        lotes_existentes = set(PajuelaSemen.objects.values_list("lote_pajuela", flat=True))

        # 1. Asegurar al menos 60 Toros Reproductores Locales
        toros_actuales = list(Bovino.objects.filter(sexo="Macho"))
        nuevos_toros = []
        for idx in range(1, 61):
            rfid_toro = f"MONCO-TORO-{idx:04d}"
            if rfid_toro not in rfids_existentes:
                rfids_existentes.add(rfid_toro)
                dias_edad = random.randint(750, 2200)
                nuevos_toros.append(
                    Bovino(
                        codigo_rfid=rfid_toro,
                        sexo="Macho",
                        fecha_nacimiento=today - timedelta(days=dias_edad),
                        raza=random.choice(razas_objs),
                        estado_actual=random.choice(["Reproductor Activo", "Activo", "Semental Élite"]),
                    )
                )
        if nuevos_toros:
            Bovino.objects.bulk_create(nuevos_toros, batch_size=200)
        toros_actuales = list(Bovino.objects.filter(sexo="Macho"))

        # 2. Asegurar al menos 105 Lotes de Pajuelas de Semen (65 locales + 40 importados EE.UU./Canadá/Europa)
        prefijos_importados = ["USA-ABS", "CAN-SEMEX", "USA-SELECT", "EUR-GEN", "ARG-CRIA"]
        nuevas_pajuelas = []
        for idx in range(1, 106):
            lote_code = f"LOTE-MONCO-{idx:03d}"
            if lote_code in lotes_existentes:
                continue
            lotes_existentes.add(lote_code)

            es_local = idx <= 65 and len(toros_actuales) > 0
            toro_asig = random.choice(toros_actuales) if es_local else None
            cod_ext = None if es_local else f"{random.choice(prefijos_importados)}-{random.randint(1000, 9999)}"
            fecha_ext = today - timedelta(days=random.randint(15, 700))
            stock_inicial = random.randint(8, 120)

            nuevas_pajuelas.append(
                PajuelaSemen(
                    lote_pajuela=lote_code,
                    toro=toro_asig,
                    codigo_toro_externo=cod_ext,
                    fecha_extraccion=fecha_ext,
                    stock=stock_inicial,
                )
            )
        if nuevas_pajuelas:
            PajuelaSemen.objects.bulk_create(nuevas_pajuelas, batch_size=200)

        todas_pajuelas = list(PajuelaSemen.objects.all())

        # 3. Asegurar más de 1.500 Vacas (Hembras) aleatorias (creamos hasta llegar a 1.550 vacas)
        estados_vaca = ["Reproductora", "Activa", "Vaquilla", "Vacía", "En Ordeña", "Preñada"]
        nuevas_vacas = []
        for idx in range(1, 1551):
            rfid_vaca = f"MONCO-VACA-{idx:04d}"
            if rfid_vaca in rfids_existentes:
                continue
            rfids_existentes.add(rfid_vaca)
            dias_edad = random.randint(450, 2600)
            pajuela_padre = random.choice(todas_pajuelas) if (todas_pajuelas and random.random() < 0.65) else None
            nuevas_vacas.append(
                Bovino(
                    codigo_rfid=rfid_vaca,
                    sexo="Hembra",
                    fecha_nacimiento=today - timedelta(days=dias_edad),
                    raza=random.choice(razas_objs),
                    pajuela_semen=pajuela_padre,
                    estado_actual=random.choice(estados_vaca),
                )
            )
        if nuevas_vacas:
            Bovino.objects.bulk_create(nuevas_vacas, batch_size=400)

        todas_vacas = list(Bovino.objects.filter(sexo="Hembra"))

        # 4. Generar relaciones de Parentesco (Madre/Padre) para trazabilidad sanguínea si hay pocas
        if Parentesco.objects.count() < 400 and len(todas_vacas) > 300:
            madres_candidatas = todas_vacas[:250]
            hijas_candidatas = todas_vacas[250:750]
            nuevos_parentescos = []
            for hija in hijas_candidatas:
                madre_bov = random.choice(madres_candidatas)
                nuevos_parentescos.append(
                    Parentesco(bovino=hija, ancestro=madre_bov, generacion=1, coef_relacion=0.5)
                )
                if hija.pajuela_semen and hija.pajuela_semen.toro:
                    nuevos_parentescos.append(
                        Parentesco(bovino=hija, ancestro=hija.pajuela_semen.toro, generacion=1, coef_relacion=0.5)
                    )
            Parentesco.objects.bulk_create(nuevos_parentescos, batch_size=400)

        # 5. Generar Inseminaciones, Diagnósticos de Gestación y Partos realistas si hay pocos
        if Inseminacion.objects.count() < 300 and todas_vacas and todas_pajuelas:
            vacas_muestra = random.sample(todas_vacas, min(420, len(todas_vacas)))
            nuevas_ins = []
            for v in vacas_muestra:
                paj = random.choice(todas_pajuelas)
                dias_atras = random.randint(1, 340)
                fecha_serv = timezone.make_aware(
                    datetime.combine(today - timedelta(days=dias_atras), time(hour=random.randint(7, 17), minute=random.choice([0, 15, 30, 45])))
                )
                nuevas_ins.append(Inseminacion(vaca=v, pajuela=paj, fecha_servicio=fecha_serv))
            Inseminacion.objects.bulk_create(nuevas_ins, batch_size=300)

            ins_sin_diag = list(Inseminacion.objects.filter(diagnosticogestacion__isnull=True)[:340])
            nuevos_diags = []
            for ins_obj in ins_sin_diag:
                r_val = random.random()
                if r_val < 0.64:
                    res = "preñada"
                    sem = random.randint(6, 36)
                elif r_val < 0.90:
                    res = "vacia"
                    sem = 0
                else:
                    res = "mortinato"
                    sem = random.randint(34, 40)

                fecha_d = min(today, ins_obj.fecha_servicio.date() + timedelta(days=random.randint(35, 90)))
                nuevos_diags.append(
                    DiagnosticoGestacion(
                        inseminacion=ins_obj,
                        resultado=res,
                        semanas=sem,
                        fecha_diagnostico=fecha_d,
                    )
                )
            DiagnosticoGestacion.objects.bulk_create(nuevos_diags, batch_size=300)

            # Crear registros de Parto (vivos y mortinatos)
            diags_creados = list(DiagnosticoGestacion.objects.filter(parto__isnull=True))
            nuevos_partos = []
            for d_obj in diags_creados:
                if d_obj.resultado == "mortinato":
                    nuevos_partos.append(
                        Parto(
                            diagnostico=d_obj,
                            cria=None,
                            fecha_parto=d_obj.fecha_diagnostico,
                            tipo_parto="Mortinato (Fallecido en Parto)",
                            observaciones="El ternero recién nacido falleció durante el parto.",
                        )
                    )
                elif d_obj.resultado == "preñada" and random.random() < 0.45:
                    nuevos_partos.append(
                        Parto(
                            diagnostico=d_obj,
                            cria=None,
                            fecha_parto=min(today, d_obj.fecha_diagnostico + timedelta(days=random.randint(10, 180))),
                            tipo_parto="Parto Natural Vivo",
                            observaciones="Parto normal registrado en predio.",
                        )
                    )
            if nuevos_partos:
                Parto.objects.bulk_create(nuevos_partos, batch_size=300)

        total_vacas = Bovino.objects.filter(sexo="Hembra").count()
        total_toros = Bovino.objects.filter(sexo="Macho").count()
        total_pajuelas = PajuelaSemen.objects.count()
        total_ins = Inseminacion.objects.count()

        self.stdout.write(
            self.style.SUCCESS(
                f"Carga masiva completada exitosamente: {total_vacas} vacas, {total_toros} toros, "
                f"{total_pajuelas} lotes de pajuelas y {total_ins} inseminaciones."
            )
        )
