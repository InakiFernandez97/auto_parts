from django.shortcuts import render, redirect
from .models import ClienteB2C
from django.contrib import messages
from .models import ClienteB2B
from .models import Producto
from django.utils import timezone
from .models import CotizacionEmpresa
from django.template.loader import get_template
from django.http import HttpResponse
from xhtml2pdf import pisa
from .models import DetalleCotizacionEmpresa
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from tienda.models import Producto
from django.views.decorators.csrf import csrf_exempt
from .models import CompraCliente, DetalleCompraCliente
from django.db.models import Q
from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.options import WebpayOptions
from transbank.common.integration_type import IntegrationType
from django.conf import settings
from django.urls import reverse


def home(request):
    productos_destacados = Producto.objects.all()[:12]
    return render(request, 'tienda/home.html', {'productos_destacados': productos_destacados})

def registro(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        apellido = request.POST.get('apellido')
        rut = request.POST.get('rut')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        contrasena = request.POST.get('contrasena')

        if ClienteB2C.objects.filter(correo=correo).exists():
            return render(request, 'registrousuario.html', {'error': 'El correo ya está registrado'})

        ClienteB2C.objects.create(
            nombre=nombre,
            apellido=apellido,
            rut=rut,
            telefono=telefono,
            correo=correo,
            contrasena=contrasena
        )
        return redirect('home')

    return render(request, 'tienda/registrousuario.html')
 

def login(request):
    if request.method == 'POST':
        correo = request.POST.get('correo')
        contrasena = request.POST.get('contrasena')

        try:
            cliente = ClienteB2C.objects.get(correo=correo, contrasena=contrasena)
            request.session['usuario_id'] = cliente.id_cliente  # <- cambio aquí
            request.session['usuario_nombre'] = cliente.nombre
            return redirect('home')
        except ClienteB2C.DoesNotExist:
            return render(request, 'home.html', {'error': 'Correo o contraseña incorrectos'})

    return redirect('home')

def login_cliente(request):
    if request.method == 'POST':
        correo = request.POST.get('correo')
        contrasena = request.POST.get('contrasena')

        try:
            cliente = ClienteB2C.objects.get(correo=correo, contrasena=contrasena)
            request.session['usuario_id'] = cliente.id_cliente
            request.session['usuario_nombre'] = cliente.nombre
            return redirect('home')
        except ClienteB2C.DoesNotExist:
            return render(request, 'tienda/logincliente.html', {'error': 'Correo o contraseña incorrectos'})

    return render(request, 'tienda/logincliente.html')


def logout(request):
    request.session.flush()
    return redirect('home')


@csrf_exempt
def agregar_al_carrito(request):
    if request.method == "POST":
        producto_id = request.POST.get("producto_id")
        cantidad = int(request.POST.get("cantidad", 1))

        carrito = request.session.get("carrito_b2c", {})
        carrito[producto_id] = carrito.get(producto_id, 0) + cantidad
        request.session["carrito_b2c"] = carrito
        request.session.modified = True

        return redirect("home") 
    return redirect("home")

def carrito_cliente(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    items = []
    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal
        items.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    return render(request, 'tienda/carrito_cliente.html', {
        'items': items,
        'total': total
    })


def catalogo_b2c(request):
    categoria = request.GET.get('categoria')
    marcas_seleccionadas = request.GET.getlist('marca')
    query = request.GET.get('q')  # 🔍 búsqueda

    productos = Producto.objects.all()

    if categoria:
        productos = productos.filter(categoria=categoria)

    if marcas_seleccionadas:
        productos = productos.filter(marca__in=marcas_seleccionadas)

    if query:
        productos = productos.filter(nombre__icontains=query)

    categorias = Producto.objects.values_list('categoria', flat=True).distinct()
    marcas = Producto.objects.values_list('marca', flat=True).distinct()

    context = {
        'productos': productos,
        'categorias': categorias,
        'marcas': marcas,
        'categoria_seleccionada': categoria,
        'marcas_seleccionadas': marcas_seleccionadas,
        'query': query  
    }

    return render(request, 'tienda/catalogo_b2c.html', context)


def catalogo_por_marca(request, nombre):
    productos = Producto.objects.filter(marca=nombre)
    categorias = Producto.objects.values_list('categoria', flat=True).distinct()
    marcas = Producto.objects.values_list('marca', flat=True).distinct()

    return render(request, 'tienda/catalogo_b2c.html', {
        'productos': productos,
        'categorias': categorias,
        'marcas': marcas,
        'marca_actual': nombre,
        'marcas_seleccionadas': [nombre],
    })

def simular_pago(request):
    if request.method == 'POST':
        total = request.POST.get('total')
        request.session['carrito_b2c'] = {}
        messages.success(request, f"¡Pago exitoso por ${total}! Se ha enviado tu boleta al correo registrado.")
        return redirect('home')
    return redirect('carrito_cliente')

def generar_compra(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = get_object_or_404(ClienteB2C, id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            messages.error(request, f"Stock insuficiente para '{producto.nombre}'.")
            return redirect('carrito_b2c')  

    compra = CompraCliente.objects.create(
    cliente=cliente,
    total=0,
    estado='Pagado',
    fecha=timezone.now()
    )


    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal

        DetalleCompraCliente.objects.create(
            compra=compra,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=subtotal
        )

        producto.stock -= cantidad
        producto.save()

    compra.total = total
    compra.save()

    # Limpiar carrito
    request.session['carrito_b2c'] = {}
    request.session.modified = True

    messages.success(request, "¡Compra realizada con éxito!")
    return redirect('perfil_cliente')

def perfil_cliente(request):
    if 'usuario_id' not in request.session:
        return redirect('home')

    try:
        cliente = ClienteB2C.objects.get(id_cliente=request.session['usuario_id'])
        compras = CompraCliente.objects.filter(cliente=cliente).order_by('-fecha')
    except ClienteB2C.DoesNotExist:
        cliente = None
        compras = []

    return render(request, 'tienda/perfil_cliente.html', {
        'cliente': cliente,
        'compras': compras
    })


def procesar_compra_cliente(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = get_object_or_404(ClienteB2C, id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            messages.error(request, f"No hay stock suficiente para '{producto.nombre}'")
            return redirect('carrito_cliente')

    compra = CompraCliente.objects.create(
        cliente=cliente,
        total=0,
        estado='Pagado',
        fecha=timezone.now()
    )

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal

        DetalleCompraCliente.objects.create(
            compra=compra,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=subtotal
        )

        producto.stock -= cantidad
        producto.save()

    compra.total = total
    compra.save()

    request.session['carrito_b2c'] = {}
    request.session.modified = True

    messages.success(request, "Compra realizada exitosamente.")
    return redirect('perfil_cliente')

def descargar_boleta(request, id):
    compra = get_object_or_404(CompraCliente, id=id)
    detalles = DetalleCompraCliente.objects.filter(compra=compra)

    template_path = 'tienda/boleta_pdf.html'
    context = {
        'compra': compra,
        'detalles': detalles
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="boleta_{compra.id}.pdf"'
    html = get_template(template_path).render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error al generar boleta', status=500)
    return response

def detalle_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    return render(request, 'tienda/detalleproducto.html', {'producto': producto})

def iniciar_pago_webpay(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        total += producto.precio * cantidad

    options = WebpayOptions(
        commerce_code=settings.TRANSBANK_COMMERCE_CODE,
        api_key=settings.TRANSBANK_API_KEY,
        integration_type=IntegrationType.TEST
    )

    transaction = Transaction()
    response = transaction.create(
        buy_order=str(request.session['usuario_id']) + '-orden',
        session_id=str(request.session['usuario_id']),
        amount=total,
        return_url=request.build_absolute_uri(reverse('webpay_return'))
    )

    return render(request, 'tienda/redireccion_webpay.html', {
        'webpay_url': response.url,
        'token': response.token

    })

@csrf_exempt
def webpay_return(request):
    token = request.POST.get("token_ws")
    if not token:
        return HttpResponse("Token no recibido", status=400)

    try:
        # Configuración global del SDK (según tu versión)
        Transaction.commerce_code = settings.TRANSBANK_COMMERCE_CODE
        Transaction.api_key = settings.TRANSBANK_API_KEY
        Transaction.integration_type = IntegrationType.TEST

        transaction = Transaction()
        response = transaction.commit(token)

        if response.status == 'AUTHORIZED':
            return redirect('procesar_compra_exitosa')
        else:
            messages.error(request, f"Pago rechazado: {response.status}")
            return redirect('carrito_cliente')

    except Exception as e:
        return HttpResponse(f"Error al procesar el pago: {str(e)}", status=500)
    
def procesar_compra_exitosa(request):
    if 'usuario_id' not in request.session:
        return redirect('logincliente')

    cliente = get_object_or_404(ClienteB2C, id_cliente=request.session['usuario_id'])
    carrito = request.session.get('carrito_b2c', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    errores_stock = []

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            errores_stock.append(producto.nombre)

    if errores_stock:
        messages.error(request, f"Sin stock para: {', '.join(errores_stock)}")
        return redirect('carrito_cliente')

    compra = CompraCliente.objects.create(
        cliente=cliente,
        total=0,
        estado='Pagado',
        fecha=timezone.now()
    )

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        subtotal = producto.precio * cantidad
        total += subtotal

        DetalleCompraCliente.objects.create(
            compra=compra,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=subtotal
        )

        producto.stock -= cantidad
        producto.save()

    compra.total = total
    compra.save()

    request.session['carrito_b2c'] = {}
    request.session.modified = True

    messages.success(request, "¡Compra realizada con éxito!")
    return redirect('perfil_cliente')


def categoria(request, categoria_nombre):
    productos_filtrados = Producto.objects.filter(categoria__iexact=categoria_nombre)
    return render(request, 'tienda/categoria.html', {
        'productos': productos_filtrados,
        'categoria': categoria_nombre
    })
""" prueba """
from django.http import HttpResponse
from django.db import connection

def ver_compras_sql_debug(request):
    if 'usuario_id' not in request.session:
        return HttpResponse("No logueado")

    cliente_id = request.session['usuario_id']
    compras = CompraCliente.objects.raw(f"SELECT * FROM compracliente WHERE id_cliente = {cliente_id}")

    resultado = "<h1>Compras desde SQL directo:</h1><ul>"
    for compra in compras:
        resultado += f"<li>Compra #{compra.id} - Total: ${compra.total}</li>"
    resultado += "</ul>"

    return HttpResponse(resultado)


""" Mayorista """
def registro_mayorista(request):
    if request.method == 'POST':
        nombre_empresa = request.POST['nombre_empresa']
        rut_empresa = request.POST['rut']
        direccion = request.POST['direccion']
        telefono = request.POST['telefono']
        correo_empresa = request.POST['correo']
        contrasena = request.POST['contrasena']

        if ClienteB2B.objects.filter(correo_empresa=correo_empresa).exists():
            messages.error(request, 'El correo ya está registrado')
            return redirect('registromayorista')

        ClienteB2B.objects.create(
            nombre_empresa=nombre_empresa,
            rut_empresa=rut_empresa,
            direccion=direccion,
            telefono=telefono,
            correo_empresa=correo_empresa,
            contrasena=contrasena
        )

        messages.success(request, '¡Te registraste en Autoparts! Ahora inicia sesión.')
        return redirect('loginmayorista')

    return render(request, 'tienda/registromayorista.html')

def login_mayorista(request):
    if request.method == 'POST':
        correo = request.POST['correo']
        contrasena = request.POST['contrasena']

        try:
            empresa = ClienteB2B.objects.get(correo_empresa=correo, contrasena=contrasena)
            request.session['mayorista_id'] = empresa.id_cliente_b2b
            request.session['mayorista_nombre'] = empresa.nombre_empresa
            return redirect('homemayorista')
        except ClienteB2B.DoesNotExist:
            return render(request, 'tienda/loginmayorista.html', {'error': 'Credenciales inválidas'})

    return render(request, 'tienda/loginmayorista.html')

def perfil_empresa(request):
    if 'mayorista_id' not in request.session:
        return redirect('home')

    try:
        empresa = ClienteB2B.objects.get(id_cliente_b2b=request.session['mayorista_id'])
    except ClienteB2B.DoesNotExist:
        return redirect('home')

    return render(request, 'tienda/perfil_empresa.html', {
        'empresa': empresa
    })

def catalogo_empresa(request):
    productos = Producto.objects.filter(stock__gt=0)  

    # Filtro por búsqueda
    query = request.GET.get("q")
    if query:
        productos = productos.filter(nombre__icontains=query)

    # Filtro por categoría
    categoria = request.GET.get("categoria")
    if categoria:
        productos = productos.filter(categoria=categoria)

    # Filtro por marcas (si vienen como checkbox múltiple)
    marcas = request.GET.getlist("marca")
    if marcas:
        productos = productos.filter(marca__in=marcas)

    # Agrega precio con descuento
    for producto in productos:
        producto.precio_con_descuento = int(producto.precio * 0.85)

    # Listas únicas para filtros
    categorias = Producto.objects.values_list('categoria', flat=True).distinct()
    marcas_carousel = Producto.objects.values_list('marca', flat=True).distinct()

    return render(request, 'tienda/catalogo_empresa.html', {
        'productos': productos,
        'categorias': categorias,
        'marcas_carousel': marcas_carousel,
        'marcas_seleccionadas': marcas,
    })

def detalle_producto_empresa(request, id):
    producto = get_object_or_404(Producto, id=id)
    precio_original = int(producto.precio)
    precio_empresa = int(precio_original * 0.85)

    return render(request, 'tienda/detalle_producto_empresa.html', {
        'producto': producto,
        'precio_original': precio_original,
        'precio_empresa': precio_empresa,
    })

def agregar_al_carrito_empresa(request):
    if request.method == 'POST':
        producto_id = str(request.POST.get('producto_id'))
        cantidad = int(request.POST.get('cantidad', 1))

        carrito = request.session.get('carrito_empresa', {})

        if producto_id in carrito:
            carrito[producto_id] += cantidad
        else:
            carrito[producto_id] = cantidad

        request.session['carrito_empresa'] = carrito
        return redirect('catalogo_empresa')

def generar_cotizacion_empresa(request):
    if 'mayorista_id' not in request.session:
        return redirect('loginmayorista')

    cliente = get_object_or_404(ClienteB2B, id_cliente_b2b=request.session['mayorista_id'])
    carrito = request.session.get('carrito_empresa', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    total = 0
    detalles = []

    # Validar stock
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        if producto.stock < cantidad:
            messages.error(request, f"El producto '{producto.nombre}' no tiene suficiente stock.")
            return redirect('cotizacion_empresa')

    # Crear cotización
    cotizacion = CotizacionEmpresa.objects.create(
        cliente=cliente,
        total=0  # se actualiza después
    )

    for producto in productos:
        cantidad = carrito[str(producto.id)]
        precio_unitario = int(producto.precio * 0.85)
        subtotal = cantidad * precio_unitario
        total += subtotal

        DetalleCotizacionEmpresa.objects.create(
            cotizacion=cotizacion,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            subtotal=subtotal
        )

        # Restar stock
        producto.stock -= cantidad
        producto.save()

    # Actualizar total en cotización
    cotizacion.total = total
    cotizacion.save()

    # Vaciar carrito
    request.session['carrito_empresa'] = {}
    request.session.modified = True

    messages.success(request, "Cotización generada correctamente.")
    return redirect('mis_cotizaciones_empresa')


def cotizacion_empresa(request):
    # Verificar si está logueado como mayorista
    if 'mayorista_id' not in request.session:
        return redirect('loginmayorista')

    cliente = get_object_or_404(ClienteB2B, id_cliente_b2b=request.session['mayorista_id'])

    carrito = request.session.get('carrito_empresa', {})
    productos = Producto.objects.filter(id__in=carrito.keys())

    items = []
    total = 0
    for producto in productos:
        cantidad = carrito[str(producto.id)]
        precio_unitario = int(producto.precio * 0.85)
        subtotal = cantidad * precio_unitario
        total += subtotal
        items.append({
            'id': producto.id,
            'nombre': producto.nombre,
            'precio': precio_unitario,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    return render(request, 'tienda/cotizacion_empresa.html', {
        'carrito': items,
        'total': total,
        'cliente': cliente
    })

def mis_cotizaciones_empresa(request):
    if 'mayorista_id' not in request.session:
        return redirect('loginmayorista')

    cliente_id = request.session['mayorista_id']
    cotizaciones = CotizacionEmpresa.objects.filter(cliente_id=cliente_id).order_by('-fecha')

    return render(request, 'tienda/mis_cotizaciones_empresa.html', {
        'cotizaciones': cotizaciones
    })

def descargar_cotizacion_pdf(request, id):
    cotizacion = CotizacionEmpresa.objects.get(id=id)
    detalles = DetalleCotizacionEmpresa.objects.filter(cotizacion=cotizacion)

    template_path = 'tienda/cotizacion_pdf.html'
    context = {
        'cotizacion': cotizacion,
        'detalles': detalles
    }

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cotizacion_{cotizacion.id}.pdf"'
    template = get_template(template_path)
    html = template.render(context)

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('Error al generar PDF', status=500)
    return response

def logout_mayorista(request):
    request.session.flush()
    return redirect('home')

def homemayorista(request):
    return render(request, 'tienda/homemayorista.html')






