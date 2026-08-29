from rest_framework import serializers

from .models import Membership, OnboardingApplication, Organization


class MembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user_id", "role", "is_active", "joined_at"]
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):
    memberships = MembershipSerializer(many=True, read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "kind", "display_name", "legal_name", "email", "phone", "website", "address_line1", "address_line2", "city", "region", "country", "verification_status", "memberships", "created_at", "updated_at"]
        read_only_fields = ["kind", "verification_status", "memberships", "created_at", "updated_at"]


class OnboardingApplicationSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer(read_only=True)

    class Meta:
        model = OnboardingApplication
        fields = ["id", "organization", "status", "review_notes", "revision_count", "submitted_at", "reviewed_at", "created_at", "updated_at"]
        read_only_fields = fields


class DesignerCreateSerializer(serializers.Serializer):
    organization = OrganizationSerializer()
    studio_name = serializers.CharField(required=False, allow_blank=True)
    portfolio_url = serializers.URLField(required=False, allow_blank=True)
    legal_registration_number = serializers.CharField(required=False, allow_blank=True)
    tax_number = serializers.CharField(required=False, allow_blank=True)
    payout_information = serializers.CharField(required=False, allow_blank=True)
    accept_terms = serializers.BooleanField()

    def validate_accept_terms(self, value):
        if not value:
            raise serializers.ValidationError("Terms must be accepted.")
        return value


class ManufacturerCreateSerializer(serializers.Serializer):
    organization = OrganizationSerializer()
    commercial_registration = serializers.CharField()
    tax_number = serializers.CharField(required=False, allow_blank=True)
    google_maps_url = serializers.URLField(required=False, allow_blank=True)
    primary_contact_person = serializers.CharField(required=False, allow_blank=True)
    contact_job_title = serializers.CharField(required=False, allow_blank=True)
    whatsapp = serializers.CharField(required=False, allow_blank=True)
    daily_capacity = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    monthly_capacity = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    payout_information = serializers.CharField(required=False, allow_blank=True)
    accept_terms = serializers.BooleanField()

    def validate_accept_terms(self, value):
        if not value:
            raise serializers.ValidationError("Terms must be accepted.")
        return value


class MemberMutationSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    role = serializers.ChoiceField(choices=Membership.Role.choices)


class VerificationDocumentCreateSerializer(serializers.Serializer):
    media_asset_id = serializers.IntegerField(min_value=1)
    document_type = serializers.ChoiceField(choices=["registration", "tax", "identity", "certification", "other"])
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
