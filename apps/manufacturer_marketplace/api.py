from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.artwork.models import DesignedProduct
from apps.media.models import MediaAsset
from apps.organizations.models import Membership, Organization
from apps.organizations.services import require_org_access
from .models import ManufacturerCapability, ManufacturerListing, ManufacturerQuote, RFQ, RFQInvitation
from .services import MANUFACTURER_QUOTE_ROLES, add_capability, add_portfolio_asset, cancel_rfq, create_rfq, decline_invitation, get_or_create_listing, open_rfq, publish_listing, select_quote, submit_quote, update_listing


class ListingSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source="organization.display_name", read_only=True)
    capabilities = serializers.SerializerMethodField()
    class Meta:
        model = ManufacturerListing
        fields = ["id","organization","organization_name","status","headline_en","headline_ar","overview_en","overview_ar","public_email","public_phone","accepts_rfq","sample_orders","min_order_quantity","lead_time_min_days","lead_time_max_days","available_monthly_capacity","materials","production_methods","markets","certifications","last_capacity_update","published_at","capabilities"]
        read_only_fields = ["id","organization","status","last_capacity_update","published_at","capabilities"]
    def get_capabilities(self, obj):
        return [{"id":c.id,"type":c.capability_type,"name":c.name,"description":c.description,"methods":c.methods,"min_quantity":c.min_quantity,"max_quantity":c.max_quantity,"lead_time_days":c.lead_time_days} for c in obj.capabilities.filter(is_active=True)]


class PublicManufacturerListAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def get(self, request):
        qs = ManufacturerListing.objects.filter(status=ManufacturerListing.Status.PUBLISHED, organization__verification_status=Organization.VerificationStatus.ACTIVE).select_related("organization").prefetch_related("capabilities")
        capability = request.query_params.get("capability")
        if capability:
            qs = qs.filter(capabilities__capability_type=capability, capabilities__is_active=True).distinct()
        return Response(ListingSerializer(qs, many=True).data)


class PublicManufacturerDetailAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def get(self, request, pk):
        obj = get_object_or_404(ManufacturerListing.objects.select_related("organization").prefetch_related("capabilities"), pk=pk, status=ManufacturerListing.Status.PUBLISHED, organization__verification_status=Organization.VerificationStatus.ACTIVE)
        return Response(ListingSerializer(obj).data)


class ManufacturerListingAPIView(APIView):
    def get(self, request, organization_id):
        org=get_object_or_404(Organization,pk=organization_id); listing=get_or_create_listing(organization=org,actor=request.user,request=request); return Response(ListingSerializer(listing).data)
    def patch(self, request, organization_id):
        org=get_object_or_404(Organization,pk=organization_id); listing=get_or_create_listing(organization=org,actor=request.user,request=request); update_listing(listing=listing,actor=request.user,data=request.data,request=request); return Response(ListingSerializer(listing).data)


class PublishListingAPIView(APIView):
    def post(self, request, listing_id):
        listing=publish_listing(listing=get_object_or_404(ManufacturerListing,pk=listing_id),actor=request.user,request=request); return Response(ListingSerializer(listing).data)


class CapabilityAPIView(APIView):
    def post(self, request, listing_id):
        listing=get_object_or_404(ManufacturerListing,pk=listing_id)
        capability=add_capability(listing=listing,actor=request.user,capability_type=request.data.get("capability_type"),name=request.data.get("name","").strip(),description=request.data.get("description",""),methods=request.data.get("methods",[]),min_quantity=request.data.get("min_quantity"),max_quantity=request.data.get("max_quantity"),lead_time_days=request.data.get("lead_time_days"),request=request)
        return Response({"id":capability.id,"type":capability.capability_type,"name":capability.name},status=201)


class PortfolioAssetAPIView(APIView):
    def post(self, request, listing_id):
        asset=add_portfolio_asset(listing=get_object_or_404(ManufacturerListing,pk=listing_id),actor=request.user,media_asset=get_object_or_404(MediaAsset,pk=request.data.get("media_asset")),caption=request.data.get("caption",""),sort_order=request.data.get("sort_order",0),request=request)
        return Response({"id":asset.id,"media_asset":asset.media_asset_id},status=201)


class RFQSerializer(serializers.ModelSerializer):
    class Meta:
        model=RFQ
        fields=["id","designer_organization","designed_product","title","quantity","size_breakdown","color_requirements","requested_methods","target_unit_price","currency","desired_delivery_date","delivery_country","delivery_city","notes","status","created_at","opened_at","selected_at"]
        read_only_fields=["id","status","created_at","opened_at","selected_at"]


class RFQListCreateAPIView(APIView):
    def get(self,request):
        qs=RFQ.objects.filter(designer_organization__memberships__user=request.user,designer_organization__memberships__is_active=True).distinct() if not request.user.is_staff else RFQ.objects.all()
        return Response(RFQSerializer(qs,many=True).data)
    def post(self,request):
        org=get_object_or_404(Organization,pk=request.data.get("designer_organization")); product=get_object_or_404(DesignedProduct,pk=request.data.get("designed_product"))
        rfq=create_rfq(designer_organization=org,actor=request.user,designed_product=product,title=request.data.get("title","").strip(),quantity=request.data.get("quantity"),size_breakdown=request.data.get("size_breakdown",{}),color_requirements=request.data.get("color_requirements",[]),requested_methods=request.data.get("requested_methods",[]),target_unit_price=request.data.get("target_unit_price"),currency=request.data.get("currency","EGP"),desired_delivery_date=request.data.get("desired_delivery_date"),delivery_country=request.data.get("delivery_country","EG"),delivery_city=request.data.get("delivery_city",""),notes=request.data.get("notes",""),request=request)
        return Response(RFQSerializer(rfq).data,status=201)


class OpenRFQAPIView(APIView):
    def post(self,request,rfq_id):
        rfq=open_rfq(rfq=get_object_or_404(RFQ,pk=rfq_id),actor=request.user,manufacturer_ids=request.data.get("manufacturer_ids",[]),request=request); return Response(RFQSerializer(rfq).data)


class ManufacturerInvitationsAPIView(APIView):
    def get(self,request,organization_id):
        org=get_object_or_404(Organization,pk=organization_id,kind=Organization.Kind.MANUFACTURER,verification_status=Organization.VerificationStatus.ACTIVE)
        require_org_access(request.user,org,roles=MANUFACTURER_QUOTE_ROLES)
        qs=RFQInvitation.objects.filter(manufacturer=org).select_related("rfq","rfq__designer_organization")
        return Response([{"id":i.id,"rfq":i.rfq_id,"title":i.rfq.title,"quantity":i.rfq.quantity,"status":i.status,"designer":i.rfq.designer_organization.display_name} for i in qs])


class SubmitQuoteAPIView(APIView):
    def post(self,request,invitation_id):
        invitation=get_object_or_404(RFQInvitation,pk=invitation_id)
        quote=submit_quote(invitation=invitation,actor=request.user,unit_price=request.data.get("unit_price"),production_lead_days=request.data.get("production_lead_days"),setup_fee=request.data.get("setup_fee",0),sample_fee=request.data.get("sample_fee",0),shipping_estimate=request.data.get("shipping_estimate",0),currency=request.data.get("currency","EGP"),minimum_order_quantity=request.data.get("minimum_order_quantity",1),sample_lead_days=request.data.get("sample_lead_days"),valid_until=request.data.get("valid_until"),notes=request.data.get("notes",""),request=request)
        return Response({"id":quote.id,"status":quote.status,"estimated_total":str(quote.estimated_total)},status=201)


class DeclineInvitationAPIView(APIView):
    def post(self,request,invitation_id):
        invitation=decline_invitation(invitation=get_object_or_404(RFQInvitation,pk=invitation_id),actor=request.user,request=request); return Response({"id":invitation.id,"status":invitation.status})


class RFQQuotesAPIView(APIView):
    def get(self,request,rfq_id):
        rfq=get_object_or_404(RFQ,pk=rfq_id); Membership.objects.get(user=request.user,organization=rfq.designer_organization,is_active=True)
        qs=ManufacturerQuote.objects.filter(invitation__rfq=rfq,status__in=[ManufacturerQuote.Status.SUBMITTED,ManufacturerQuote.Status.ACCEPTED,ManufacturerQuote.Status.DECLINED]).select_related("invitation__manufacturer")
        return Response([{"id":q.id,"manufacturer":q.invitation.manufacturer.display_name,"manufacturer_id":q.invitation.manufacturer_id,"unit_price":str(q.unit_price),"currency":q.currency,"production_lead_days":q.production_lead_days,"moq":q.minimum_order_quantity,"estimated_total":str(q.estimated_total),"status":q.status,"valid_until":q.valid_until} for q in qs])


class SelectQuoteAPIView(APIView):
    def post(self,request,quote_id):
        selection=select_quote(quote=get_object_or_404(ManufacturerQuote,pk=quote_id),actor=request.user,request=request); return Response({"id":selection.id,"rfq":selection.rfq_id,"manufacturer":selection.manufacturer_id,"quote":selection.quote_id},status=201)


class CancelRFQAPIView(APIView):
    def post(self,request,rfq_id):
        rfq=cancel_rfq(rfq=get_object_or_404(RFQ,pk=rfq_id),actor=request.user,request=request); return Response(RFQSerializer(rfq).data)
