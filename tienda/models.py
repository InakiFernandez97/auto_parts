from django.db import models
from django.utils import timezone
from datetime import datetime

class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    precio = models.IntegerField()
    precio_empresa = models.IntegerField(blank=True, null=True)  # campo opcional si no se calcula dinámicamente
    categoria = models.CharField(max_length=50, blank=True, null=True)
    subcategoria = models.CharField(max_length=50, blank=True, null=True)
    marca = models.CharField(max_length=50, blank=True, null=True)
    origen = models.CharField(max_length=50, blank=True, null=True)
    aplicacion = models.CharField(max_length=50, blank=True, null=True)
    promocion = models.BooleanField(default=False)
    imagen = models.CharField(max_length=255, blank=True, null=True)
    stock = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'Producto'
        managed = False
    
class ClienteB2C(models.Model):
    id_cliente = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=50)
    apellido = models.CharField(max_length=50)
    rut = models.CharField(max_length=12, unique=True)
    telefono = models.CharField(max_length=12)
    correo = models.EmailField(unique=True)
    contrasena = models.CharField(max_length=128)

    class Meta:
        db_table = 'cliente_b2c'
        managed = False

class CompraCliente(models.Model):
    cliente = models.ForeignKey('ClienteB2C', on_delete=models.CASCADE, db_column='id_cliente')
    fecha = models.DateTimeField(auto_now_add=True)
    total = models.IntegerField()
    estado = models.CharField(max_length=50)

    class Meta:
        db_table = 'compracliente'
        managed = True  

    def __str__(self):
        return f"Compra #{self.id} - {self.cliente.nombre}"

class DetalleCompraCliente(models.Model):
    compra = models.ForeignKey(
        CompraCliente, 
        on_delete=models.CASCADE, 
        db_column='compra_id', 
        related_name='detalles'
    )
    producto = models.ForeignKey('Producto', on_delete=models.CASCADE, db_column='producto_id')
    cantidad = models.IntegerField()
    precio_unitario = models.IntegerField()
    subtotal = models.IntegerField()

    class Meta:
        db_table = 'detallecompracliente'
        managed = False  

""" Mayorista """
class ClienteB2B(models.Model):
    id_cliente_b2b = models.AutoField(primary_key=True)
    nombre_empresa = models.CharField(max_length=100)
    rut_empresa = models.CharField(max_length=12, unique=True)
    direccion = models.CharField(max_length=255)
    telefono = models.CharField(max_length=12)
    correo_empresa = models.EmailField(unique=True)
    contrasena = models.CharField(max_length=128)

    class Meta:
        db_table = 'cliente_b2b'
        managed = False

class CotizacionEmpresa(models.Model):
    cliente = models.ForeignKey(ClienteB2B, on_delete=models.CASCADE, db_column='cliente_id')
    fecha = models.DateTimeField(auto_now_add=True)
    total = models.IntegerField()
    estado = models.CharField(max_length=50, default='Pendiente')

    class Meta:
        db_table = 'cotizacion_empresa'
        managed = False

class DetalleCotizacionEmpresa(models.Model):
    cotizacion = models.ForeignKey(CotizacionEmpresa, on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.IntegerField()
    precio_unitario = models.IntegerField()
    subtotal = models.IntegerField()

    class Meta:
        db_table = 'detalle_cotizacion_empresa'
        managed = False