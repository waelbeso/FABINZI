import 'package:flutter/widgets.dart';

class L10n {
  const L10n._();

  static const supportedLocales = [Locale('en'), Locale('ar')];

  static const Map<String, Map<String, String>> _strings = {
    'en': {
      'appName': 'FABINZI', 'discover': 'Discover', 'artwork': 'Artwork', 'studio': 'Studio', 'purchases': 'Purchases', 'account': 'Account',
      'cart': 'Cart', 'notifications': 'Notifications', 'search': 'Search', 'retry': 'Retry', 'cancel': 'Cancel', 'save': 'Save', 'close': 'Close', 'continue': 'Continue',
      'signIn': 'Sign in', 'signOut': 'Sign out', 'username': 'Username', 'password': 'Password', 'signInRequired': 'Sign in to continue', 'sessionExpired': 'Your session expired. Please sign in again.',
      'noData': 'Nothing here yet', 'unavailable': 'Unavailable', 'offline': 'Connection unavailable', 'requestFailed': 'Something went wrong', 'loading': 'Loading…',
      'products': 'Products', 'stores': 'Stores', 'all': 'All', 'customizable': 'Customizable', 'variants': 'Options', 'addToCart': 'Add to cart', 'customize': 'Customize', 'outOfStock': 'Unavailable',
      'designer': 'Designer', 'productionMethod': 'Production method', 'print': 'Print', 'embroidery': 'Embroidery', 'details': 'Details',
      'projects': 'Projects', 'newProject': 'New project', 'draft': 'Draft', 'ready': 'Ready', 'quantity': 'Quantity', 'notes': 'Notes', 'validate': 'Validate', 'markReady': 'Mark Ready', 'checkout': 'Checkout',
      'addText': 'Add text', 'addArtwork': 'Add artwork', 'uploadImage': 'Upload image', 'delete': 'Delete', 'moveResizeRotate': 'Drag, pinch and rotate', 'zone': 'Decoration zone',
      'subtotal': 'Subtotal', 'shipping': 'Shipping', 'discount': 'Discount', 'total': 'Total', 'remove': 'Remove', 'emptyCart': 'Your cart is empty', 'reviewCheckout': 'Review checkout',
      'name': 'Name', 'phone': 'Phone', 'email': 'Email', 'address1': 'Address', 'address2': 'Address line 2', 'city': 'City', 'region': 'Region', 'country': 'Country', 'postalCode': 'Postal code',
      'paymentMethod': 'Payment method', 'placeOrder': 'Place purchase', 'placingOrder': 'Placing purchase…', 'paymentPending': 'Payment confirmation is handled by the server.',
      'purchase': 'Purchase', 'items': 'Items', 'status': 'Status', 'fulfillment': 'Fulfillment', 'tracking': 'Tracking', 'carrier': 'Carrier', 'trackingNumber': 'Tracking number', 'noTracking': 'Tracking is not available yet.',
      'markAllRead': 'Mark all read', 'preferences': 'Preferences', 'emailNotifications': 'Email notifications', 'smsNotifications': 'SMS notifications', 'smsPhone': 'SMS phone (E.164)',
      'settings': 'Settings', 'language': 'Language', 'english': 'English', 'arabic': 'العربية', 'theme': 'Theme', 'system': 'System', 'light': 'Light', 'dark': 'Dark',
      'profile': 'Profile', 'unsupportedAccountActions': 'Password reset, account activation and social login are not available in this version.', 'guest': 'Guest', 'browseAsGuest': 'You can browse products and approved artwork without signing in.',
      'fileTooLarge': 'The image exceeds the 10 MiB limit.', 'unsupportedImage': 'Choose a PNG, JPEG or WebP image.', 'uploading': 'Uploading…', 'validationPassed': 'Studio validation passed.', 'validationFailed': 'Studio needs attention.',
      'conflictRefresh': 'The server reports a conflicting state. Refresh before trying again.', 'rateLimited': 'Too many requests. Please try again later.', 'serviceUnavailable': 'The service is temporarily unavailable.',
      'refresh': 'Refresh', 'open': 'Open', 'back': 'Back', 'filter': 'Filter', 'clear': 'Clear', 'created': 'Created', 'leadTime': 'Lead time', 'days': 'days',
    },
    'ar': {
      'appName': 'FABINZI', 'discover': 'اكتشف', 'artwork': 'الأعمال الفنية', 'studio': 'الاستوديو', 'purchases': 'المشتريات', 'account': 'الحساب',
      'cart': 'السلة', 'notifications': 'الإشعارات', 'search': 'بحث', 'retry': 'إعادة المحاولة', 'cancel': 'إلغاء', 'save': 'حفظ', 'close': 'إغلاق', 'continue': 'متابعة',
      'signIn': 'تسجيل الدخول', 'signOut': 'تسجيل الخروج', 'username': 'اسم المستخدم', 'password': 'كلمة المرور', 'signInRequired': 'سجّل الدخول للمتابعة', 'sessionExpired': 'انتهت الجلسة. يرجى تسجيل الدخول مرة أخرى.',
      'noData': 'لا توجد بيانات حالياً', 'unavailable': 'غير متاح', 'offline': 'الاتصال غير متاح', 'requestFailed': 'حدث خطأ', 'loading': 'جارٍ التحميل…',
      'products': 'المنتجات', 'stores': 'المتاجر', 'all': 'الكل', 'customizable': 'قابل للتخصيص', 'variants': 'الخيارات', 'addToCart': 'أضف للسلة', 'customize': 'خصّص', 'outOfStock': 'غير متاح',
      'designer': 'المصمم', 'productionMethod': 'طريقة الإنتاج', 'print': 'طباعة', 'embroidery': 'تطريز', 'details': 'التفاصيل',
      'projects': 'المشروعات', 'newProject': 'مشروع جديد', 'draft': 'مسودة', 'ready': 'جاهز', 'quantity': 'الكمية', 'notes': 'ملاحظات', 'validate': 'تحقق', 'markReady': 'اعتماد جاهز', 'checkout': 'إتمام الشراء',
      'addText': 'أضف نصاً', 'addArtwork': 'أضف عملاً فنياً', 'uploadImage': 'ارفع صورة', 'delete': 'حذف', 'moveResizeRotate': 'اسحب وكبّر ودوّر', 'zone': 'منطقة التخصيص',
      'subtotal': 'الإجمالي الفرعي', 'shipping': 'الشحن', 'discount': 'الخصم', 'total': 'الإجمالي', 'remove': 'إزالة', 'emptyCart': 'السلة فارغة', 'reviewCheckout': 'مراجعة الطلب',
      'name': 'الاسم', 'phone': 'الهاتف', 'email': 'البريد الإلكتروني', 'address1': 'العنوان', 'address2': 'العنوان الثاني', 'city': 'المدينة', 'region': 'المنطقة', 'country': 'الدولة', 'postalCode': 'الرمز البريدي',
      'paymentMethod': 'طريقة الدفع', 'placeOrder': 'تأكيد الشراء', 'placingOrder': 'جارٍ تأكيد الشراء…', 'paymentPending': 'تأكيد الدفع يتم من خلال الخادم.',
      'purchase': 'المشتريات', 'items': 'العناصر', 'status': 'الحالة', 'fulfillment': 'التنفيذ', 'tracking': 'التتبع', 'carrier': 'شركة الشحن', 'trackingNumber': 'رقم التتبع', 'noTracking': 'بيانات التتبع غير متاحة بعد.',
      'markAllRead': 'تحديد الكل كمقروء', 'preferences': 'التفضيلات', 'emailNotifications': 'إشعارات البريد', 'smsNotifications': 'إشعارات الرسائل', 'smsPhone': 'رقم الرسائل (E.164)',
      'settings': 'الإعدادات', 'language': 'اللغة', 'english': 'English', 'arabic': 'العربية', 'theme': 'المظهر', 'system': 'النظام', 'light': 'فاتح', 'dark': 'داكن',
      'profile': 'الملف الشخصي', 'unsupportedAccountActions': 'استعادة كلمة المرور وتفعيل الحساب وتسجيل الدخول الاجتماعي غير متاحة في هذا الإصدار.', 'guest': 'زائر', 'browseAsGuest': 'يمكنك تصفح المنتجات والأعمال الفنية المعتمدة بدون تسجيل الدخول.',
      'fileTooLarge': 'حجم الصورة يتجاوز 10 MiB.', 'unsupportedImage': 'اختر صورة PNG أو JPEG أو WebP.', 'uploading': 'جارٍ الرفع…', 'validationPassed': 'تم اجتياز تحقق الاستوديو.', 'validationFailed': 'الاستوديو يحتاج إلى مراجعة.',
      'conflictRefresh': 'الخادم يبلّغ عن تعارض في الحالة. حدّث البيانات قبل المحاولة.', 'rateLimited': 'طلبات كثيرة. حاول لاحقاً.', 'serviceUnavailable': 'الخدمة غير متاحة مؤقتاً.',
      'refresh': 'تحديث', 'open': 'فتح', 'back': 'رجوع', 'filter': 'تصفية', 'clear': 'مسح', 'created': 'تاريخ الإنشاء', 'leadTime': 'مدة التجهيز', 'days': 'أيام',
    },
  };

  static String t(BuildContext context, String key) {
    final code = Localizations.localeOf(context).languageCode == 'ar' ? 'ar' : 'en';
    return _strings[code]?[key] ?? _strings['en']?[key] ?? key;
  }

  static bool get hasParity {
    final en = _strings['en']!.keys.toSet();
    final ar = _strings['ar']!.keys.toSet();
    return en.length == ar.length && en.containsAll(ar) && ar.containsAll(en);
  }
}
