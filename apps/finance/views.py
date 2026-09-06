from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.organizations.models import Membership, Organization

from .models import FinanceAccount, SettlementRequest
from .services import account_balance


@login_required
def finance_dashboard(request):
    memberships = (
        Membership.objects.filter(
            user=request.user,
            is_active=True,
            role__in=[
                Membership.Role.OWNER,
                Membership.Role.MANAGER,
                Membership.Role.ACCOUNTANT,
            ],
            organization__verification_status=Organization.VerificationStatus.ACTIVE,
        )
        .select_related("organization")
    )
    rows = []
    for membership in memberships:
        for account in FinanceAccount.objects.filter(
            organization=membership.organization
        ):
            rows.append(
                {
                    "organization": membership.organization,
                    "account": account,
                    "balance": account_balance(account),
                }
            )
    organization_ids = [membership.organization_id for membership in memberships]
    settlements = SettlementRequest.objects.filter(
        organization_id__in=organization_ids
    ).select_related("organization")[:100]
    return render(
        request,
        "finance/dashboard.html",
        {"rows": rows, "settlements": settlements},
    )


@login_required
def designer_finance(request):
    return finance_dashboard(request)


@login_required
def manufacturer_finance(request):
    return finance_dashboard(request)
