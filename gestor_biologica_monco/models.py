import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Q

# --- Funciones Generadoras y Filtros ---

def generar_rfid():
    return str(uuid.uuid4().hex)[:12].upper()

def generar_lote():
    return f"LOTE-{str(uuid.uuid4().hex)[:8].upper()}"

def generar_toro_externo():
    return f"EXT-{str(uuid.uuid4().hex)[:8].upper()}"

def vacas_disponibles():
    from .models import DiagnosticoGestacion, Bovino, Inseminacion
    # 1. Vacas con diagnóstico de preñez registrado
    vacas_prenadas = DiagnosticoGestacion.objects.filter(
        resultado__icontains='preñad'
    ).values_list('inseminacion__vaca', flat=True)
    
    # 2. Vacas con inseminación reciente que aún no tienen diagnóstico registrado
    vacas_pendientes = Inseminacion.objects.filter(
        diagnosticogestacion__isnull=True
    ).values_list('vaca', flat=True)
    
    # Retorna las hembras excluyendo las preñadas y las pendientes de diagnóstico
    return Bovino.objects.filter(sexo='Hembra').exclude(
        id_bovino__in=vacas_prenadas
    ).exclude(
        id_bovino__in=vacas_pendientes
    ).exclude(
        estado_actual__icontains='preñad'
    )

def inseminaciones_disponibles():
    from .models import DiagnosticoGestacion
    # Inseminaciones que ya tienen un diagnóstico asociado
    inseminaciones_diagnosticadas = DiagnosticoGestacion.objects.values_list('inseminacion_id', flat=True)
    return ~Q(id_inseminacion__in=inseminaciones_diagnosticadas)

def diagnosticos_disponibles():
    from .models import Parto
    # Diagnósticos que YA tienen un parto registrado
    diagnosticos_con_parto = Parto.objects.values_list('diagnostico_id', flat=True)
    # Solo diagnósticos de "preñada" que NO tengan un parto asociado
    return Q(resultado='preñada') & ~Q(id_diagnostico__in=diagnosticos_con_parto)


# --- Modelos Base ---

class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    nombre_rol = models.CharField(max_length=50)
    descripcion = models.TextField()
    def __str__(self): return self.nombre_rol

class Predio(models.Model):
    id_predio = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    ubicacion = models.CharField(max_length=150)
    def __str__(self): return self.nombre

class Usuario(models.Model):
    rut = models.CharField(max_length=12, primary_key=True)
    nombre_completo = models.CharField(max_length=100)
    rol = models.ForeignKey(Rol, on_delete=models.RESTRICT, db_column='id_rol')
    predio = models.ForeignKey(Predio, on_delete=models.RESTRICT, db_column='id_predio')
    fecha_ingreso = models.DateTimeField()
    def __str__(self): return self.nombre_completo

class Parcela(models.Model):
    id_parcela = models.AutoField(primary_key=True)
    predio = models.ForeignKey(Predio, on_delete=models.CASCADE, db_column='id_predio')
    codigo = models.CharField(max_length=20)
    def __str__(self): return self.codigo

class Lote(models.Model):
    id_lote = models.AutoField(primary_key=True)
    parcela = models.ForeignKey(Parcela, on_delete=models.CASCADE, db_column='id_parcela')
    nombre_lote = models.CharField(max_length=50)
    descripcion = models.TextField()
    def __str__(self): return self.nombre_lote

class TipoReporte(models.Model):
    id_tipo_reporte = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=80)
    descripcion = models.TextField()
    vista_sql = models.CharField(max_length=80)
    def __str__(self): return self.nombre

class ReporteGenerado(models.Model):
    id_reporte = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, db_column='usuario_rut')
    tipo_reporte = models.ForeignKey(TipoReporte, on_delete=models.CASCADE, db_column='id_tipo_reporte')
    filtros = models.JSONField()
    fecha_generacion = models.DateTimeField(auto_now_add=True)


# --- Modelos de Ganado ---

class Raza(models.Model):
    id_raza = models.AutoField(primary_key=True)
    nombre_raza = models.CharField(max_length=50)
    origen = models.CharField(max_length=50)
    def __str__(self): return self.nombre_raza

class Madre(models.Model):
    id_madregenero = models.AutoField(primary_key=True)
    sexo = models.CharField(max_length=10)
    fecha_nacimiento = models.DateField()
    estado_actual = models.CharField(max_length=20)
    def __str__(self): return f"Madre ID {self.id_madregenero} - {self.estado_actual}"

class Bovino(models.Model):
    SEXO_CHOICES = [
        ('Hembra', 'Vaca (Hembra)'),
        ('Macho', 'Toro (Macho)'),
    ]
    id_bovino = models.AutoField(primary_key=True)
    codigo_rfid = models.CharField(max_length=50, unique=True, default=generar_rfid)
    sexo = models.CharField(max_length=10, choices=SEXO_CHOICES)
    fecha_nacimiento = models.DateField()
    raza = models.ForeignKey(Raza, on_delete=models.RESTRICT, db_column='id_raza')
    madre = models.ForeignKey(Madre, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_madre')
    pajuela_semen = models.ForeignKey('PajuelaSemen', on_delete=models.SET_NULL, null=True, blank=True, db_column='pajuela_semen')
    estado_actual = models.CharField(max_length=20)
    def __str__(self): return self.codigo_rfid

class PajuelaSemen(models.Model):
    id_pajuela = models.AutoField(primary_key=True)
    toro = models.ForeignKey(Bovino, on_delete=models.RESTRICT, db_column='id_toro', related_name='pajuelas', limit_choices_to={'sexo': 'Macho'}, null=True, blank=True)
    codigo_toro_externo = models.CharField(max_length=50, null=True, blank=True, default=generar_toro_externo, help_text="Completar solo si es semen importado y no hay toro local.")
    lote_pajuela = models.CharField(max_length=30, default=generar_lote, unique=True)
    fecha_extraccion = models.DateField()
    stock = models.IntegerField()
    def __str__(self):
        if self.toro:
            return f"Pajuela {self.lote_pajuela} (Toro local: {self.toro.codigo_rfid})"
        return f"Pajuela {self.lote_pajuela} (Toro USA: {self.codigo_toro_externo})"

class Parentesco(models.Model):
    id_parentesco = models.AutoField(primary_key=True)
    bovino = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_bovino', related_name='parentescos_bovino')
    ancestro = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_ancestro', related_name='parentescos_ancestro')
    generacion = models.IntegerField()
    coef_relacion = models.DecimalField(max_digits=5, decimal_places=4)

class CoeficienteConsanguinidad(models.Model):
    id_coef = models.AutoField(primary_key=True)
    bovino = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_bovino')
    valor_f = models.DecimalField(max_digits=5, decimal_places=4)
    generaciones_eval = models.IntegerField()
    fecha_calculo = models.DateTimeField()

class AlertaConsanguinidad(models.Model):
    id_alerta = models.AutoField(primary_key=True)
    vaca = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_vaca', related_name='alertas_vaca')
    toro = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_toro', related_name='alertas_toro')
    f_proyectado = models.DecimalField(max_digits=5, decimal_places=4)
    fecha = models.DateTimeField()
    estado = models.CharField(max_length=20)


# --- Procesos Reproductivos y Diagnósticos ---

class Inseminacion(models.Model):
    id_inseminacion = models.AutoField(primary_key=True)
    vaca = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_vaca', limit_choices_to=vacas_disponibles)
    pajuela = models.ForeignKey(PajuelaSemen, on_delete=models.RESTRICT, db_column='id_pajuela')
    fecha_servicio = models.DateTimeField()

    def clean(self):
        if hasattr(self, 'vaca'):
            ya_prenada = DiagnosticoGestacion.objects.filter(
                inseminacion__vaca=self.vaca,
                resultado__icontains='preñad'
            ).exclude(inseminacion=self).exists()
            if ya_prenada or 'preñad' in (self.vaca.estado_actual or '').lower():
                raise ValidationError("No se puede inseminar: Esta vaca ya se encuentra preñada.")
        if hasattr(self, 'vaca') and hasattr(self, 'pajuela') and self.pajuela.toro:
            toro_semen = self.pajuela.toro
            if self.vaca.pajuela_semen and self.vaca.pajuela_semen.toro == toro_semen:
                raise ValidationError("ALERTA CONSANGUINIDAD: No se puede guardar. El toro de esta pajuela es el padre de la vaca.")
            if self.vaca.madre and toro_semen.madre and self.vaca.madre == toro_semen.madre:
                raise ValidationError("ALERTA CONSANGUINIDAD: No se puede guardar. La vaca y el toro comparten la misma madre.")

    def __str__(self):
        return f"Vaca {self.vaca.codigo_rfid} - {self.fecha_servicio.strftime('%d/%m/%Y')}"

class DiagnosticoGestacion(models.Model):
    RESULTADO_CHOICES = [
        ('preñada', 'Preñada'),
        ('vacia', 'Vacía'),
    ]
    id_diagnostico = models.AutoField(primary_key=True)
    inseminacion = models.ForeignKey(Inseminacion, on_delete=models.CASCADE, db_column='id_inseminacion', limit_choices_to=inseminaciones_disponibles)
    resultado = models.CharField(max_length=15, choices=RESULTADO_CHOICES)
    semanas = models.IntegerField()
    fecha_diagnostico = models.DateField()
    
    def clean(self):
        if self.resultado == 'preñada' and hasattr(self, 'inseminacion'):
            existe_prenez = DiagnosticoGestacion.objects.filter(
                inseminacion__vaca=self.inseminacion.vaca,
                resultado='preñada',
                parto__isnull=True
            ).exclude(pk=self.pk).exists()
            if existe_prenez:
                raise ValidationError("Esta vaca ya se encuentra con un embarazo activo sin parir.")
                
    def __str__(self): 
        return f"Diagnóstico {self.inseminacion.vaca.codigo_rfid} - {self.resultado}"

class Parto(models.Model):
    id_parto = models.AutoField(primary_key=True)
    diagnostico = models.ForeignKey(DiagnosticoGestacion, on_delete=models.RESTRICT, db_column='id_diagnostico', limit_choices_to=diagnosticos_disponibles)
    cria = models.ForeignKey(Bovino, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_cria', related_name='parto_cria')
    fecha_parto = models.DateField()
    tipo_parto = models.CharField(max_length=30)
    observaciones = models.TextField()
    def __str__(self): 
        return f"Parto {self.fecha_parto} - Cría {self.cria}"

class MovimientoBovino(models.Model):
    id_movimiento = models.AutoField(primary_key=True)
    bovino = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_bovino')
    lote_origen = models.ForeignKey(Lote, on_delete=models.SET_NULL, null=True, db_column='id_lote_origen', related_name='movimientos_salida')
    lote_destino = models.ForeignKey(Lote, on_delete=models.SET_NULL, null=True, db_column='id_lote_destino', related_name='movimientos_entrada')
    fecha = models.DateTimeField()
    motivo = models.CharField(max_length=100)

class ControlPeso(models.Model):
    id_peso = models.AutoField(primary_key=True)
    bovino = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_bovino')
    peso_kg = models.DecimalField(max_digits=6, decimal_places=2)
    fecha_pesaje = models.DateField()