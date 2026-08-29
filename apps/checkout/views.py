from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from apps.storefront.models import StudioProject
from .models import CheckoutSession, CustomerOrder
from .services import create_checkout, place_order, require_checkout_owner, update_checkout_shipping

@login_required
def checkout_start(request, project_id):
    project=get_object_or_404(StudioProject,pk=project_id)
    try: session=create_checkout(project=project,actor=request.user,request=request)
    except (ValidationError,PermissionDenied) as exc: return render(request,"checkout/error.html",{"error":str(exc)},status=400)
    return redirect("checkout-detail",pk=session.pk)

@login_required
def checkout_detail(request,pk):
    session=get_object_or_404(CheckoutSession.objects.select_related("studio_project__product","studio_project__variant"),pk=pk)
    try: require_checkout_owner(request.user,session)
    except PermissionDenied: return render(request,"checkout/error.html",{"error":"Checkout access denied."},status=403)
    if request.method=="POST":
        try:
            if request.POST.get("action")=="shipping": update_checkout_shipping(session=session,actor=request.user,request=request,shipping_name=request.POST.get("shipping_name",""),shipping_phone=request.POST.get("shipping_phone",""),shipping_email=request.POST.get("shipping_email",""),shipping_address1=request.POST.get("shipping_address1",""),shipping_address2=request.POST.get("shipping_address2",""),shipping_city=request.POST.get("shipping_city",""),shipping_region=request.POST.get("shipping_region",""),shipping_country=request.POST.get("shipping_country","EG"),postal_code=request.POST.get("postal_code",""))
            elif request.POST.get("action")=="place":
                order,_=place_order(session=session,actor=request.user,payment_method=request.POST.get("payment_method","cod"),request=request); return redirect("order-detail",pk=order.pk)
        except (ValidationError,PermissionDenied) as exc: return render(request,"checkout/detail.html",{"checkout":session,"error":str(exc)})
    return render(request,"checkout/detail.html",{"checkout":session})

@login_required
def orders(request): return render(request,"checkout/orders.html",{"orders":CustomerOrder.objects.filter(customer=request.user)})
@login_required
def order_detail(request,pk):
    order=get_object_or_404(CustomerOrder.objects.select_related("item"),pk=pk)
    if order.customer_id!=request.user.pk and not request.user.is_staff: return render(request,"checkout/error.html",{"error":"Order access denied."},status=403)
    return render(request,"checkout/order_detail.html",{"order":order})
