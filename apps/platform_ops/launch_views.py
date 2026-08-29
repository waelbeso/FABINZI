from django.shortcuts import render

from .seo import page_seo


PUBLIC_TRUST_PAGES = {
    "about": {
        "title": {"en": "About FABINZI", "ar": "عن FABINZI"},
        "description": {
            "en": "How FABINZI connects customers, designers and manufacturing partners from product discovery through production and fulfillment.",
            "ar": "كيف تربط FABINZI العملاء والمصممين وشركاء التصنيع من اكتشاف المنتج حتى الإنتاج والتنفيذ.",
        },
        "intro": {
            "en": "FABINZI is a digital fashion platform that coordinates design, customer commerce and distributed manufacturing. Designers create; manufacturing partners produce; customers buy; FABINZI coordinates the workflow.",
            "ar": "FABINZI منصة أزياء رقمية تنسّق بين التصميم وتجارة العملاء والتصنيع الموزع. يبدع المصمم، وينتج شريك التصنيع، ويشتري العميل، وتنسّق FABINZI سير العمل.",
        },
        "sections": {
            "en": [
                ("What customers can do", "Browse published products and artwork, buy ready products, and use optional Studio customization when a product supports it."),
                ("What designers do", "Designers manage their creative work, products, storefronts, manufacturing RFQs and business visibility through the Designer workspace."),
                ("What manufacturers do", "Manufacturers are production partners. They publish capabilities, respond to RFQs, quote production work, execute production and QC, pack orders and record shipment/tracking through the canonical fulfillment flow."),
            ],
            "ar": [
                ("ما الذي يمكن للعميل فعله", "استعراض المنتجات والأعمال الفنية المنشورة، وشراء المنتجات الجاهزة، واستخدام تخصيص الاستوديو الاختياري عندما يدعمه المنتج."),
                ("دور المصمم", "يدير المصمم أعماله الإبداعية ومنتجاته ومتجره وطلبات عروض التصنيع وبياناته التجارية من مساحة عمل المصمم."),
                ("دور المصنع", "المصنع شريك إنتاج وليس بائع كتالوج. ينشر قدراته، ويرد على طلبات العروض، ويقدم عروض الإنتاج، وينفذ الإنتاج والجودة والتعبئة ويسجل الشحن والتتبع عبر مسار التنفيذ المعتمد."),
            ],
        },
    },
    "terms": {
        "title": {"en": "Terms of Service", "ar": "شروط الاستخدام"},
        "description": {"en": "Baseline terms for using the FABINZI web platform.", "ar": "الشروط الأساسية لاستخدام منصة FABINZI على الويب."},
        "intro": {
            "en": "These baseline terms describe the current product behavior. They are repository launch copy and are not represented as lawyer-reviewed terms. The platform operator should complete jurisdiction-specific legal review before public production launch.",
            "ar": "تصف هذه الشروط الأساسية سلوك المنتج الحالي. وهي نص إطلاق داخل المستودع ولا يتم تقديمها على أنها تمت مراجعتها قانونيًا. يجب على مشغل المنصة استكمال المراجعة القانونية المناسبة للاختصاص قبل الإطلاق العام للإنتاج.",
        },
        "sections": {
            "en": [
                ("Accounts", "Users are responsible for keeping account credentials secure and for activity performed through their account. Privileged platform administration is protected by multi-factor authentication."),
                ("Marketplace roles", "Designers publish creative/product work and manufacturing partners provide production services. A Manufacturer is a production partner, not a customer-facing catalog seller."),
                ("Orders", "A checkout creates one customer purchase with operational child orders for the purchased lines. Product, pricing and fulfillment information shown by the platform is based on persisted platform records."),
                ("Creative rights", "Users must only upload or use content they are entitled to use. FABINZI records rights declarations where the product flow requires them."),
                ("External services", "Payments, email, SMS, object storage and monitoring may depend on optional external providers. Availability depends on what the platform operator has actually configured and enabled."),
            ],
            "ar": [
                ("الحسابات", "يتحمل المستخدم مسؤولية الحفاظ على سرية بيانات الدخول والنشاط المنفذ من خلال حسابه. الإدارة ذات الصلاحيات المرتفعة محمية بالمصادقة متعددة العوامل."),
                ("أدوار المنصة", "ينشر المصممون الأعمال الإبداعية والمنتجات، ويقدم شركاء التصنيع خدمات الإنتاج. المصنع شريك إنتاج وليس بائع كتالوج موجهًا للعميل."),
                ("الطلبات", "ينشئ الدفع عملية شراء واحدة للعميل مع طلبات تشغيلية فرعية لسطور الشراء. تعتمد معلومات المنتج والسعر والتنفيذ المعروضة على سجلات محفوظة فعليًا في المنصة."),
                ("حقوق المحتوى", "يجب ألا يرفع المستخدم أو يستخدم إلا المحتوى الذي يملك حق استخدامه. تسجل FABINZI إقرارات الحقوق عندما يتطلب مسار المنتج ذلك."),
                ("الخدمات الخارجية", "قد تعتمد المدفوعات والبريد والرسائل النصية وتخزين الملفات والمراقبة على مزودين خارجيين اختياريين. ويتوقف توفرها على ما قام مشغل المنصة بتهيئته وتفعيله فعليًا."),
            ],
        },
    },
    "privacy": {
        "title": {"en": "Privacy Policy", "ar": "سياسة الخصوصية"},
        "description": {"en": "Baseline privacy information for FABINZI web users.", "ar": "معلومات الخصوصية الأساسية لمستخدمي FABINZI على الويب."},
        "intro": {
            "en": "This page explains the categories of data the current platform handles. It does not claim a specific legal certification or jurisdictional compliance review. A production operator must finalize the legally required notices for its launch markets.",
            "ar": "توضح هذه الصفحة فئات البيانات التي تتعامل معها المنصة الحالية. ولا تدعي حصول المنصة على شهادة قانونية أو مراجعة امتثال لاختصاص محدد. يجب على مشغل الإنتاج استكمال الإشعارات القانونية المطلوبة لأسواق الإطلاق.",
        },
        "sections": {
            "en": [
                ("Account and business data", "FABINZI stores account information and, where relevant, Designer or Manufacturer organization, membership and operational profile data."),
                ("Commerce data", "The platform stores carts, checkout shipping/contact details, purchases, child orders, commercial snapshots, production state and fulfillment/tracking records needed to operate the service."),
                ("Creative and uploaded data", "Design, artwork and Studio files may be stored as public or private media according to their access classification. Private media is served through application authorization rather than an unrestricted public object URL."),
                ("Operational security data", "The platform records audit events and operational metadata needed for authorization, security and workflow accountability. Integration secrets are encrypted in storage and are not intended to be exposed through the browser."),
                ("External processors", "Optional payment, messaging, storage and monitoring providers receive data only when those integrations are actually configured and invoked for their documented purpose."),
            ],
            "ar": [
                ("بيانات الحساب والأعمال", "تخزن FABINZI معلومات الحساب، وعند الحاجة بيانات جهة المصمم أو المصنع والعضويات والملفات التشغيلية."),
                ("بيانات التجارة", "تخزن المنصة السلة وبيانات الشحن والاتصال عند الدفع وعمليات الشراء والطلبات الفرعية واللقطات التجارية وحالة الإنتاج وسجلات التنفيذ والتتبع اللازمة لتشغيل الخدمة."),
                ("البيانات الإبداعية والملفات", "قد تُحفظ ملفات التصميم والأعمال الفنية والاستوديو كوسائط عامة أو خاصة وفق تصنيف الوصول. تمر الوسائط الخاصة عبر تفويض التطبيق بدل رابط كائن عام غير مقيد."),
                ("بيانات الأمن والتشغيل", "تسجل المنصة أحداث التدقيق والبيانات التشغيلية اللازمة للتفويض والأمن ومساءلة سير العمل. يتم تشفير أسرار التكامل في التخزين ولا يفترض عرضها في المتصفح."),
                ("المعالجون الخارجيون", "لا تستقبل خدمات الدفع أو الرسائل أو التخزين أو المراقبة الاختيارية البيانات إلا عندما تكون مهيأة فعليًا ويتم استدعاؤها لغرضها الموثق."),
            ],
        },
    },
    "returns": {
        "title": {"en": "Refunds & Returns", "ar": "الاسترداد والمرتجعات"},
        "description": {"en": "How refund and return requests should be handled at the FABINZI launch baseline.", "ar": "كيفية التعامل مع طلبات الاسترداد والمرتجعات في خط أساس إطلاق FABINZI."},
        "intro": {
            "en": "FABINZI currently records orders, payments and fulfillment state but the repository does not define a universal automatic refund/return entitlement. Final commercial and statutory return rules must be published by the platform operator for each launch market before taking production orders.",
            "ar": "تسجل FABINZI حاليًا حالة الطلبات والمدفوعات والتنفيذ، لكن المستودع لا يحدد حقًا آليًا موحدًا للاسترداد أو الإرجاع. يجب على مشغل المنصة نشر قواعد الإرجاع التجارية والقانونية النهائية لكل سوق إطلاق قبل استقبال طلبات الإنتاج.",
        },
        "sections": {
            "en": [
                ("Order-specific review", "Any refund, cancellation or return decision should reference the persisted customer purchase/order and its payment, production and fulfillment state."),
                ("Customized goods", "Studio-customized or made-to-order items may require different handling from standard stock items. No blanket return promise is made by this baseline page."),
                ("Payment providers", "If an online payment provider is enabled, any monetary refund must use the operator-approved provider process and must not be inferred solely from changing an internal order status."),
            ],
            "ar": [
                ("مراجعة كل طلب", "يجب أن يستند أي قرار استرداد أو إلغاء أو إرجاع إلى عملية الشراء أو الطلب المحفوظ وحالة الدفع والإنتاج والتنفيذ الخاصة به."),
                ("المنتجات المخصصة", "قد تحتاج المنتجات المخصصة في الاستوديو أو المصنوعة حسب الطلب إلى معالجة مختلفة عن المنتجات المخزنة القياسية. ولا تقدم هذه الصفحة وعدًا عامًا بالإرجاع."),
                ("مزودو الدفع", "إذا تم تفعيل مزود دفع إلكتروني فيجب تنفيذ أي استرداد مالي عبر العملية المعتمدة من المشغل لدى المزود، ولا يجوز افتراض حدوث استرداد لمجرد تغيير حالة الطلب داخليًا."),
            ],
        },
    },
    "shipping": {
        "title": {"en": "Shipping & Fulfillment", "ar": "الشحن والتنفيذ"},
        "description": {"en": "How FABINZI represents production, packing, shipping and tracking.", "ar": "كيف تمثل FABINZI الإنتاج والتعبئة والشحن والتتبع."},
        "intro": {
            "en": "FABINZI separates manufacturing from fulfillment. Manufacturing partners progress assigned production work through production, QC and packing; shipment/tracking is recorded on the canonical fulfillment record linked to the customer order.",
            "ar": "تفصل FABINZI بين التصنيع والتنفيذ. يتقدم شريك التصنيع في العمل المسند عبر الإنتاج والجودة والتعبئة، ويتم تسجيل الشحن والتتبع على سجل التنفيذ المعتمد المرتبط بطلب العميل.",
        },
        "sections": {
            "en": [
                ("Tracking visibility", "When a shipment/tracking record has been created and is authorized for the customer, the customer order experience can show the persisted carrier and tracking information."),
                ("Delivery estimates", "No universal delivery SLA is claimed by this page. Timing depends on the actual product, production state, configured fulfillment arrangements and carrier information."),
                ("Manufacturing role", "Manufacturers remain production partners; shipment data is part of fulfillment and does not create a separate seller or shipment-commerce model."),
            ],
            "ar": [
                ("إظهار التتبع", "عند إنشاء سجل شحن وتتبع وإتاحته للعميل وفق الصلاحيات يمكن لواجهة الطلب عرض شركة الشحن ومعلومات التتبع المحفوظة فعليًا."),
                ("مواعيد التسليم", "لا تدعي هذه الصفحة وجود مدة تسليم موحدة. يعتمد التوقيت على المنتج الفعلي وحالة الإنتاج وترتيبات التنفيذ المهيأة ومعلومات شركة الشحن."),
                ("دور المصنع", "يظل المصنع شريك إنتاج؛ وبيانات الشحن جزء من التنفيذ ولا تنشئ نموذج بائع أو تجارة شحن موازية."),
            ],
        },
    },
    "support": {
        "title": {"en": "Contact & Support", "ar": "التواصل والدعم"},
        "description": {"en": "Support guidance for FABINZI customers and business partners.", "ar": "إرشادات الدعم لعملاء FABINZI وشركائها التجاريين."},
        "intro": {
            "en": "Use your FABINZI account and the persisted purchase/order identifiers when requesting order-specific help. Public support coordinates must be configured and published by the platform operator before production launch; this repository does not invent an email address or phone number.",
            "ar": "استخدم حساب FABINZI وأرقام عملية الشراء أو الطلب المحفوظة عند طلب مساعدة تخص طلبًا. يجب على مشغل المنصة تهيئة ونشر وسائل التواصل العامة قبل الإطلاق الإنتاجي؛ ولا ينشئ هذا المستودع بريدًا إلكترونيًا أو رقم هاتف غير حقيقي.",
        },
        "sections": {
            "en": [
                ("Customer support", "Keep the customer purchase number and affected order line available so support can identify the persisted transaction."),
                ("Designer and Manufacturer support", "Business partners should identify their organization and the relevant RFQ, quote, production job or fulfillment record when requesting operational support."),
                ("Security", "Do not send passwords, MFA/TOTP secrets, payment-provider credentials or integration secrets in a support request."),
            ],
            "ar": [
                ("دعم العميل", "احتفظ برقم عملية الشراء وسطر الطلب المعني حتى يمكن للدعم تحديد المعاملة المحفوظة."),
                ("دعم المصمم والمصنع", "على شركاء الأعمال تحديد الجهة وطلب العرض أو العرض أو مهمة الإنتاج أو سجل التنفيذ ذي الصلة عند طلب دعم تشغيلي."),
                ("الأمن", "لا ترسل كلمات المرور أو أسرار المصادقة متعددة العوامل أو بيانات مزود الدفع أو أسرار التكامل في طلب دعم."),
            ],
        },
    },
}


def public_trust_page(request, page_key):
    page = PUBLIC_TRUST_PAGES[page_key]
    language = getattr(request, "LANGUAGE_CODE", "en")
    language = "ar" if language == "ar" else "en"
    title = page["title"][language]
    description = page["description"][language]
    context = {
        "trust_page": {
            "key": page_key,
            "title": title,
            "intro": page["intro"][language],
            "sections": page["sections"][language],
        },
        "page_seo": page_seo(title=f"{title} | FABINZI", description=description),
    }
    return render(request, "platform_ops/public_trust.html", context)


def bad_request(request, exception=None):
    return render(request, "errors/400.html", status=400)


def csrf_failure(request, reason=""):
    return render(request, "errors/csrf.html", status=403)
