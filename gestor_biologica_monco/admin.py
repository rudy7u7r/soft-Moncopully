from django.contrib import admin
from .models import (
    Rol, Predio, Usuario, Parcela, Lote, TipoReporte, ReporteGenerado,
    Raza, Madre, Bovino, PajuelaSemen, Parentesco, CoeficienteConsanguinidad,
    AlertaConsanguinidad, Inseminacion, DiagnosticoGestacion, Parto,
    MovimientoBovino, ControlPeso
)

admin.site.register(Rol)
admin.site.register(Predio)
admin.site.register(Usuario)
admin.site.register(Parcela)
admin.site.register(Lote)
admin.site.register(TipoReporte)
admin.site.register(ReporteGenerado)
admin.site.register(Raza)
admin.site.register(Madre)
admin.site.register(Bovino)
admin.site.register(PajuelaSemen)
admin.site.register(Parentesco)
admin.site.register(CoeficienteConsanguinidad)
admin.site.register(AlertaConsanguinidad)
admin.site.register(Inseminacion)
admin.site.register(DiagnosticoGestacion)
admin.site.register(Parto)
admin.site.register(MovimientoBovino)
admin.site.register(ControlPeso)