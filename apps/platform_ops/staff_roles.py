"""Deterministic FABINZI internal staff roles for the productized Control Center.

These are Django staff groups, never Designer/Manufacturer Organization memberships.
No role in this module includes integrations permissions; integrations remain a
superuser-only platform-owner boundary.
"""

ROLE_PLATFORM_OPERATIONS = "FABINZI — Platform Operations Manager"
ROLE_PARTNER_ONBOARDING = "FABINZI — Partner Onboarding & Success"
ROLE_CREATIVE_IP = "FABINZI — Creative & IP Team"
ROLE_MANUFACTURING_OPERATIONS = "FABINZI — Manufacturing Operations"
ROLE_FINANCE = "FABINZI — Finance"
ROLE_CUSTOMER_SUPPORT = "FABINZI — Customer Support"
ROLE_CONTENT_MARKETPLACE = "FABINZI — Content & Marketplace"
ROLE_AUDITOR = "FABINZI — Auditor / Read Only"

ROLE_SPECS = {
    ROLE_PLATFORM_OPERATIONS: {
        "view_apps": ("accounts", "organizations", "checkout", "operations", "manufacturer_marketplace", "public_inquiries", "notifications", "platform_ops"),
        "extra_permissions": (
            "accounts.change_user",
            "organizations.change_organization",
            "organizations.change_onboardingapplication",
            "operations.change_productionjob",
        ),
    },
    ROLE_PARTNER_ONBOARDING: {
        "view_apps": ("organizations", "public_profiles", "public_inquiries"),
        "extra_permissions": (
            "organizations.change_organization",
            "organizations.change_onboardingapplication",
            "public_profiles.change_professionalpublicstate",
            "public_profiles.change_manufacturercapabilityverification",
            "public_profiles.change_manufacturerpublicproductapproval",
        ),
    },
    ROLE_CREATIVE_IP: {
        "view_apps": ("design", "artwork", "public_profiles"),
        "extra_permissions": (
            "design.change_garmentdesignversion",
            "design.add_technicalreview",
            "artwork.change_artworkversion",
            "artwork.add_artworkreview",
            "artwork.change_ipcase",
        ),
    },
    ROLE_MANUFACTURING_OPERATIONS: {
        "view_apps": ("manufacturer_marketplace", "operations", "public_profiles", "checkout"),
        "extra_permissions": (
            "operations.change_productionjob",
            "public_profiles.change_manufacturercapabilityverification",
            "public_profiles.change_manufacturerpublicproductapproval",
        ),
    },
    ROLE_FINANCE: {
        "view_apps": ("finance", "subscriptions", "checkout", "organizations"),
        "extra_permissions": (
            "finance.change_payoutprofile",
            "finance.change_settlementrequest",
            "finance.add_financeadjustment",
            "finance.view_finance_policy_governance",
            "finance.manage_finance_policy_governance",
            "finance.activate_finance_policy_governance",
            "finance.reconcile_finance_recognition",
            "finance.execute_finance_payout",
            "subscriptions.manage_professional_subscription",
            "subscriptions.add_subscriptionbillingconfirmation",
        ),
    },
    ROLE_CUSTOMER_SUPPORT: {
        "view_apps": ("accounts", "checkout", "notifications", "public_inquiries"),
        "extra_permissions": (),
    },
    ROLE_CONTENT_MARKETPLACE: {
        "view_apps": ("storefront", "public_profiles", "artwork"),
        "extra_permissions": (
            "storefront.change_storefront",
            "storefront.change_storeproduct",
            "public_profiles.change_professionalpublicstate",
            "public_profiles.change_manufacturerpublicproductapproval",
        ),
    },
    ROLE_AUDITOR: {
        "view_apps": (
            "accounts", "audit", "artwork", "checkout", "design", "finance",
            "manufacturer_marketplace", "notifications", "operations", "organizations",
            "platform_ops", "public_inquiries", "public_profiles", "storefront", "subscriptions",
        ),
        "extra_permissions": (),
    },
}

ROLE_NAMES = tuple(ROLE_SPECS)
