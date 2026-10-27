from django.db import models

class Rol(models.Model):
    id_rol = models.AutoField(primary_key=True)
    nombre_rol = models.CharField(max_length=50)
    descripcion = models.TextField()

    def __str__(self):
        return self.nombre_rol

class Predio(models.Model):
    id_predio = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    ubicacion = models.CharField(max_length=150)

    def __str__(self):
        return self.nombre

class Usuario(models.Model):
    rut = models.CharField(max_length=12, primary_key=True)
    nombre_completo = models.CharField(max_length=100)
    rol = models.ForeignKey(Rol, on_delete=models.RESTRICT, db_column='id_rol')
    predio = models.ForeignKey(Predio, on_delete=models.RESTRICT, db_column='id_predio')
    fecha_ingreso = models.DateTimeField()

    def __str__(self):
        return self.nombre_completo

class Parcela(models.Model):
    id_parcela = models.AutoField(primary_key=True)
    predio = models.ForeignKey(Predio, on_delete=models.CASCADE, db_column='id_predio')
    codigo = models.CharField(max_length=20)

    def __str__(self):
        return self.codigo

class Lote(models.Model):
    id_lote = models.AutoField(primary_key=True)
    parcela = models.ForeignKey(Parcela, on_delete=models.CASCADE, db_column='id_parcela')
    nombre_lote = models.CharField(max_length=50)
    descripcion = models.TextField()

    def __str__(self):
        return self.nombre_lote

class TipoReporte(models.Model):
    id_tipo_reporte = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=80)
    descripcion = models.TextField()
    vista_sql = models.CharField(max_length=80)

    def __str__(self):
        return self.nombre

class ReporteGenerado(models.Model):
    id_reporte = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, db_column='usuario_rut')
    tipo_reporte = models.ForeignKey(TipoReporte, on_delete=models.CASCADE, db_column='id_tipo_reporte')
    filtros = models.JSONField()
    fecha_generacion = models.DateTimeField(auto_now_add=True)

class Raza(models.Model):
    id_raza = models.AutoField(primary_key=True)
    nombre_raza = models.CharField(max_length=50)
    origen = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre_raza

class Madre(models.Model):
    id_madregenero = models.AutoField(primary_key=True)
    sexo = models.CharField(max_length=10)
    fecha_nacimiento = models.DateField()
    estado_actual = models.CharField(max_length=20)

class Bovino(models.Model):
    id_bovino = models.AutoField(primary_key=True)
    codigo_rfid = models.CharField(max_length=50, unique=True)
    sexo = models.CharField(max_length=10)
    fecha_nacimiento = models.DateField()
    raza = models.ForeignKey(Raza, on_delete=models.RESTRICT, db_column='id_raza')
    madre = models.ForeignKey(Madre, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_madre')
    pajuela_semen = models.ForeignKey('PajuelaSemen', on_delete=models.SET_NULL, null=True, blank=True, db_column='pajuela_semen')
    estado_actual = models.CharField(max_length=20)

    def __str__(self):
        return self.codigo_rfid

class PajuelaSemen(models.Model):
    id_pajuela = models.AutoField(primary_key=True)
    toro = models.ForeignKey(Bovino, on_delete=models.RESTRICT, db_column='id_toro', related_name='pajuelas')
    lote_pajuela = models.CharField(max_length=30)
    fecha_extraccion = models.DateField()
    stock = models.IntegerField()

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

class Inseminacion(models.Model):
    id_inseminacion = models.AutoField(primary_key=True)
    vaca = models.ForeignKey(Bovino, on_delete=models.CASCADE, db_column='id_vaca')
    pajuela = models.ForeignKey(PajuelaSemen, on_delete=models.RESTRICT, db_column='id_pajuela')
    fecha_servicio = models.DateTimeField()

class DiagnosticoGestacion(models.Model):
    RESULTADO_CHOICES = [
        ('preñada', 'Preñada'),
        ('vacia', 'Vacía'),
    ]
    id_diagnostico = models.AutoField(primary_key=True)
    inseminacion = models.ForeignKey(Inseminacion, on_delete=models.CASCADE, db_column='id_inseminacion')
    resultado = models.CharField(max_length=15, choices=RESULTADO_CHOICES)
    semanas = models.IntegerField()
    fecha_diagnostico = models.DateField()

class Parto(models.Model):
    id_parto = models.AutoField(primary_key=True)
    diagnostico = models.ForeignKey(DiagnosticoGestacion, on_delete=models.RESTRICT, db_column='id_diagnostico')
    cria = models.ForeignKey(Bovino, on_delete=models.SET_NULL, null=True, blank=True, db_column='id_cria', related_name='parto_cria')
    fecha_parto = models.DateField()
    tipo_parto = models.CharField(max_length=30)
    observaciones = models.TextField()

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