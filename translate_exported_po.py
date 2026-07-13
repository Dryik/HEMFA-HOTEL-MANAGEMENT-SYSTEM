import os
import re
import sys


def po_escape(text):
    """Escape a term for inclusion in a quoted PO msgid/msgstr."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )

TRANSLATIONS = {
    "Address": "العنوان",
    "Admin Use": "استخدام إداري",
    "Agencies / Entities": "الوكالات / الجهات",
    "Agency / Entity": "الوكالة / الجهة",
    "All Nationalities": "كل الجنسيات",
    "Already Charged": "تم المحاسبة بالفعل",
    "Amenities": "الخدمات المرافقة",
    "Amenities beyond the room type's standard set.": "الخدمات الإضافية خارج المجموعة الأساسية لنوع الغرفة.",
    "Amount": "المبلغ",
    "Amount Due": "المبلغ المستحق",
    "Amount Paid": "المبلغ المدفوع",
    "Amount Posted": "المبلغ المسجل",
    "Applies this rate depending on the guest's nationality.": "يطبق هذا السعر حسب جنسية النزيل.",
    "Are you sure you want to close this cashier session? This will lock transactions and calculate differences.": "هل أنت متأكد من رغبتك في إغلاق جلسة الصندوق هذه؟ سيتم قفل المعاملات واحتساب الفروقات.",
    "Are you sure you want to run the night audit? This will post room-night charges, close no-shows, and roll the operational business date forward.": "هل أنت متأكد من تشغيل التدقيق الليلي؟ سيتم ترحيل رسوم الغرف وإغلاق حالات عدم الحضور وتدوير تاريخ العمل الفندقي.",
    "Arrival": "الوصول",
    "Arrival Date": "تاريخ الوصول",
    "Arrivals Today": "الواصلون اليوم",
    "Assign a room before confirming.": "يرجى تخصيص غرفة قبل تأكيد الحجز.",
    "Audit": "التدقيق",
    "Audit Action": "إجراء التدقيق",
    "Audit Date": "تاريخ التدقيق",
    "Audit Details": "تفاصيل التدقيق",
    "Audit Parameters": "معايير التدقيق",
    "Audit Reference": "مرجع التدقيق",
    "Base Nightly Price": "سعر الليلة الأساسي",
    "Bill-to entity (جهة) this stay is registered under.": "الجهة المسؤول عن دفع الفاتورة المسجل تحتها هذا الحجز.",
    "Billed To": "مفوتر إلى",
    "Business Day Start": "بداية يوم العمل",
    "Cancel": "إلغاء",
    "Cancelled": "ملغي",
    "Cash Verification Summary": "ملخص مطابقة النقدية",
    "Cashier": "أمين الصندوق / موظف الاستقبال",
    "Cashier Sessions": "جلسات الاستقبال والصندوق",
    "Check In": "تسجيل دخول",
    "Checked In": "داخل الفندق / مسجل دخول",
    "Checked Out": "مغادر / مسجل خروج",
    "Clean": "نظيفة",
    "Close Session": "إغلاق الجلسة",
    "Closed": "مغلقة",
    "Closed Time": "وقت الإغلاق",
    "Closing Cash Control": "مطابقة النقدية عند الإغلاق",
    "Closing Cash Count": "جرد النقدية عند الإغلاق",
    "Closing Count": "عد الإغلاق",
    "Company": "الشركة",
    "Company / Entity": "الشركة / الجهة",
    "Company Currency": "عملة الشركة",
    "Completed": "مكتمل",
    "Configuration": "الإعدادات",
    "Confirm": "تأكيد",
    "Confirm Check Out": "تأكيد تسجيل الخروج",
    "Confirmed": "مؤكد",
    "Counts toward availability and the occupancy denominator.": "يحتسب ضمن الغرف الشاغرة ومقام الإشغال.",
    "Create Agency Invoice": "إنشاء فاتورة الوكالة",
    "Create Guest Invoice": "إنشاء فاتورة النزيل",
    "Currency": "العملة",
    "Current Business Date": "تاريخ العمل الحالي",
    "Dashboard": "لوحة التحكم",
    "Date": "التاريخ",
    "Date of Birth": "تاريخ الميلاد",
    "Default Agency / Entity": "الوكالة / الجهة الافتراضية",
    "Default nightly rate before seasonal, agency and occupancy adjustments (hotel_rate).": "السعر الافتراضي لليلة قبل التسويات الموسمية والوكالات ونسب الإشغال (hotel_rate).",
    "Departure": "المغادرة",
    "Departures Today": "المغادرون اليوم",
    "Description": "الوصف",
    "Difference": "الفارق",
    "Dirty": "غير نظيفة",
    "Draft": "مسودة",
    "Drives the LYD vs foreign-currency pricing rule (hotel_rate).": "يتحكم في قاعدة تسعير العملة المحلية مقابل العملة الأجنبية (hotel_rate).",
    "Driving License": "رخصة قيادة",
    "End Date": "تاريخ الانتهاء",
    "Entity responsible for this specific charge line.": "الجهة المسؤولة عن خط الفاتورة هذا.",
    "Entity this guest is usually registered under. The reservation can override it per stay.": "الجهة التي يسجل تحتها النزيل غالباً، ويمكن للحجز تجاوزها لكل إقامة.",
    "Extra Amenities": "وسائل راحة إضافية",
    "Family": "عائلي",
    "Family Book": "كتيب العائلة",
    "Female": "أنثى",
    "Financials": "المالية",
    "Floor": "الطابق",
    "Floors": "الطوابق",
    "Folio": "حساب النزيل / الفوليو",
    "Folio Count": "عدد حسابات النزلاء",
    "Folio Lines": "خطوط حساب النزيل",
    "Folio Number": "رقم حساب النزيل",
    "Folio Routing Rules": "قواعد توجيه الحسابات",
    "Folios": "حسابات النزلاء / الفوليو",
    "Foreigner": "أجنبي",
    "Front Desk": "مكتب الاستقبال",
    "Front Desk Cashier Session": "جلسة صندوق الاستقبال",
    "Front Desk Sessions": "جلسات صندوق الاستقبال",
    "Gender": "الجنس",
    "Group": "مجموعة",
    "Guest": "النزيل / الضيف",
    "Guest Nationality Type": "نوع جنسية النزيل",
    "Guests": "النزلاء",
    "Hotel": "الفندق",
    "Hotel Floor": "الطابق الفندقي",
    "Hotel Folio Ledger": "دفتر حسابات الفندق (الفوليو)",
    "Hotel Folio Line": "خط حساب الفندق (الفوليو)",
    "Hotel Folio Routing Rule": "قاعدة توجيه حسابات الفندق",
    "Hotel Guest": "نزيل الفندق",
    "Hotel Night Audit": "التدقيق الليلي للفندق",
    "Hotel Night Audit Detail Line": "تفاصيل التدقيق الليلي للفندق",
    "Hotel Property": "المنشأة الفندقية",
    "Hotel Rate Occupancy Band": "شريحة إشغال الأسعار",
    "Hotel Rate Rule": "قاعدة تسعير الفندق",
    "Hotel Reservation": "حجز الفندق",
    "Hotel Room": "غرفة الفندق",
    "Hour at which the hotel business day rolls over. A stay is charged per business day from this hour to the same hour the next calendar day.": "الساعة التي يتم عندها تدوير يوم العمل الفندقي؛ تحتسب الإقامة لكل يوم عمل من هذه الساعة حتى الساعة نفسها من اليوم التالي.",
    "Hours after the business day start during which checkout incurs no late charge.": "الساعات الممنوحة بعد بداية يوم العمل لتسجيل المغادرة بدون رسوم تأخير.",
    "Housekeeping Status": "حالة نظافة الغرفة",
    "ID Expiry": "تاريخ انتهاء الهوية",
    "ID Number": "رقم الهوية",
    "ID Type": "نوع الهوية",
    "Identification Document": "وثيقة الهوية",
    "Identity": "الهوية",
    "If checked, nightly rate will not be updated automatically by seasonal pricing or occupancy bands.": "عند التفعيل، لن يتغير سعر الليلة تلقائياً بالمواسم أو شرائح الإشغال.",
    "If checked, the charge is locked (e.g. invoiced or processed by night audit).": "عند التفعيل، تكون الرسوم مقفلة (مفوترة أو مرحلة بالتدقيق الليلي).",
    "In House": "نزلاء الفندق حالياً",
    "Individual": "فردي",
    "Inspected": "مفتشة ومفحوصة",
    "Internal notes...": "ملاحظات داخلية...",
    "Invoice": "فاتورة",
    "Invoice Line": "خط الفاتورة",
    "Invoices": "الفواتير",
    "Is Agency / Entity": "هل هي وكالة / جهة؟",
    "Late Checkout Grace (hours)": "مهلة تسجيل المغادرة المتأخر (بالساعات)",
    "Leave empty for a room type shared across all properties.": "اتركه فارغاً لنوع غرفة مشترك في كل الفنادق.",
    "Ledger / Charges": "الدفتر / الرسوم والخدمات",
    "Libyan National": "نزيل ليبي",
    "Libyan national number (الرقم الوطني).": "الرقم الوطني الليبي.",
    "Male": "ذكر",
    "Max Occupancy (%)": "الحد الأقصى للإشغال (%)",
    "Min Occupancy (%)": "الحد الأدنى للإشغال (%)",
    "Multiplication factor to apply to the nightly rate (e.g. 1.20 for +20% price).": "معامل الضرب المطبق على سعر الليلة (مثال: 1.20 لزيادة 20% في السعر).",
    "National ID": "البطاقة الشخصية",
    "National Number": "الرقم الوطني",
    "Nationality": "الجنسية",
    "New": "جديد",
    "Night Audit": "التدقيق الليلي",
    "Night Audits": "التدقيق الليلي",
    "Nightly Rate": "سعر الليلة",
    "No Show": "عدم حضور",
    "No Show Rollover": "ترحيل عدم الحضور",
    "No uninvoiced lines found for this payee.": "لا توجد خطوط غير مفوترة لهذا العميل لدفعها.",
    "Occupancy": "الإشغال",
    "Occupancy Bands": "شرائح الإشغال",
    "Occupancy Rate (%)": "نسبة الإشغال (%)",
    "Occupied": "مشغولة",
    "Only cancelled or no-show reservations can be reset.": "يمكن فقط إعادة تهيئة الحجوزات الملغاة أو التي سجلت كعدم حضور.",
    "Only confirmed reservations can be no-show.": "يمكن فقط تسجيل عدم حضور للحجوزات المؤكدة.",
    "Only confirmed reservations can check in.": "يمكن فقط تسجيل الدخول للحجوزات المؤكدة.",
    "Only draft or confirmed reservations can be cancelled.": "يمكن فقط إلغاء الحجوزات المسودة أو المؤكدة.",
    "Only draft reservations can be confirmed.": "يمكن فقط تأكيد الحجوزات المسودة.",
    "Only in-house reservations can check out.": "يمكن فقط تسجيل المغادرة للنزلاء المقيمين فعلياً.",
    "Open": "مفتوحة",
    "Opened Time": "وقت الفتح",
    "Opening Cash Control": "مطابقة النقدية عند الفتح",
    "Opening Cash Count": "جرد النقدية عند الفتح",
    "Opening Count": "عد الفتح",
    "Operational business date being closed.": "تاريخ العمل الفندقي الجاري إغلاقه بالتدقيق الليلي.",
    "Other": "أخرى",
    "Out of Order": "خارج الخدمة",
    "Passport": "جواز سفر",
    "Place of Birth": "مكان الميلاد",
    "Please define the closing cash count before closing the session.": "الرجاء إدخال قيمة جرد النقدية قبل إغلاق الجلسة.",
    "Posted": "مرحل / مسجل",
    "Pricing": "التسعير",
    "Pricing & Conditions": "التسعير والشروط",
    "Product": "المنتج",
    "Product Category": "فئة المنتج",
    "Product category that triggers this routing rule.": "فئة المنتج التي تفعل قاعدة التوجيه الفوليو هذه.",
    "Profession": "المهنة",
    "Properties": "الفنادق / المنشآت",
    "Property": "الفندق / المنشأة",
    "Quantity": "الكمية",
    "Rate Locked": "قفل السعر",
    "Rate Multiplier": "مضاعف السعر",
    "Rate Product": "منتج تسعير الغرفة",
    "Rate Rules": "قواعد التسعير",
    "Reservation": "الحجز",
    "Reservation Number": "رقم الحجز",
    "Reservation Planning": "مخطط الحجوزات",
    "Reservations": "الحجوزات",
    "Reserved": "محجوزة",
    "Reset to Draft": "إعادة إلى مسودة",
    "Results": "النتائج",
    "Revenue Posted": "الإيرادات المسجلة والملغاة",
    "Room": "الغرفة",
    "Room Amenity": "وسيلة راحة الغرفة",
    "Room Charge - %s": "رسوم الغرفة - %s",
    "Room Night Charged": "ليلة غرفة محتسبة",
    "Room Number": "رقم الغرفة",
    "Room Type": "نوع الغرفة",
    "Room Types": "أنواع الغرف",
    "Room reserved for hotel administration; excluded from sellable inventory and occupancy percentages.": "غرفة محجوزة للاستخدام الإداري، مستبعدة من الغرف القابلة للبيع ونسب الإشغال.",
    "Rooms": "الغرف",
    "Rooms available for sale: excludes out-of-order and admin-use rooms. Denominator for occupancy-based pricing.": "الغرف القابلة للبيع: باستثناء غرف خارج الخدمة والاستخدام الإداري؛ وهي مقام حساب التسعير حسب الإشغال.",
    "Route To": "توجيه الحساب إلى",
    "Route to Agency": "توجيه إلى الوكالة / الجهة",
    "Route to Guest": "توجيه إلى النزيل",
    "Routing Details": "تفاصيل التوجيه للحسابات",
    "Routing Rules": "قواعد توجيه حسابات الفوليو",
    "Rule Info": "معلومات قاعدة التسعير",
    "Run By": "تشغيل بواسطة",
    "Run Night Audit": "بدء التدقيق الليلي",
    "Service product carrying the base price, taxes and income account for this room type. Created automatically if empty.": "الخدمة التي تحمل السعر الأساسي والضرائب وحساب الإيراد لهذا النوع من الغرف. تنشأ تلقائياً إذا تركت فارغة.",
    "Session": "الجلسة",
    "Session Cash Entry": "إدخال نقدية الجلسة",
    "Session Info": "معلومات الجلسة",
    "Session Reference": "مرجع الجلسة",
    "Set by an open room-impacting maintenance request. Removes the room from sellable inventory.": "يتم تفعيله بطلب صيانة مفتوح يؤثر على الغرفة؛ يسحب الغرفة من الغرف القابلة للبيع.",
    "Short code used in references and reports.": "كود اختصار مستخدم في المراجع والتقارير.",
    "Specific Agency / Entity": "وكالة / جهة محددة",
    "Specific agency to route to. If left empty, routes to the reservation's agency.": "الوكالة المحددة للتوجيه. إذا تركت فارغة يتم التوجيه لوكالة الحجز.",
    "Start Date": "تاريخ البدء",
    "Status": "الحالة",
    "Stay": "الحجز والإقامة",
    "Stay Reference": "مرجع الإقامة",
    "Taxes": "الضرائب",
    "The active operational business date for the hotel, rolled forward daily by the night audit.": "تاريخ العمل الفندقي النشط، يتم تدويره يومياً بواسطة التدقيق الليلي.",
    "This night audit is already completed.": "تم إكمال هذا التدقيق الليلي بالفعل.",
    "This session is already closed.": "هذه الجلسة مغلقة بالفعل.",
    "Timeframes": "المدد الزمنية",
    "Total Charges": "إجمالي الرسوم والخدمات",
    "Total Closing Balance": "إجمالي رصيد الإغلاق",
    "Total Opening Balance": "إجمالي رصيد الفتح",
    "Total Transactions": "إجمالي المعاملات والدفعات",
    "Travel agency, company or government entity (جهة) that can be billed for its guests and hold advance balances.": "وكالة سفر أو شركة أو جهة حكومية يمكن فوترة نزلائها عليها والاحتفاظ بأرصدة مقدمة لها.",
    "Trip": "الرحلة / الزيارة",
    "Type": "النوع",
    "Unit Price": "سعر الوحدة",
    "Vacant": "شاغرة",
    "active": "نشط",
    "adults": "البالغين",
    "amount": "المبلغ",
    "cancelled": "ملغاة",
    "checkout": "مغادرة",
    "children": "الأطفال",
    "closing": "إغلاق",
    "code": "الرمز",
    "confirmed": "مؤكد",
    "date": "التاريخ",
    "description": "الوصف",
    "details": "التفاصيل",
    "difference": "الفارق",
    "dirty": "غير نظيفة",
    "draft": "مسودة",
    "floors": "الطوابق",
    "help": "مساعدة",
    "multiplier": "المضاعف",
    "name": "الاسم",
    "nights": "الليالي",
    "notes": "الملاحظات",
    "occupied": "مشغولة",
    "opening": "فتح",
    "sequence": "التسلسل",
    "state": "الحالة",
    "status": "الحالة",
    "type": "النوع",
    "vacant": "شاغرة"
}

# Terms for the modules implemented after the original dictionary:
# hotel_maintenance, hotel_restricted_services, hotel_pos_room_charge,
# hotel_reports.
TRANSLATIONS.update({
    # hotel_maintenance
    "Maintenance": "الصيانة",
    "Maintenance Requests": "طلبات الصيانة",
    "Hotel Maintenance Request": "طلب صيانة الفندق",
    "Request Reference": "مرجع الطلب",
    "Reported By": "جهة التبليغ",
    "Reporting Guest": "النزيل المبلغ",
    "Guest who reported the problem, when the source is a guest.": "النزيل الذي أبلغ عن المشكلة عندما يكون مصدر البلاغ نزيلاً.",
    "Blocks Room": "يحجب الغرفة عن البيع",
    "Technician": "الفني",
    "Location": "الموقع",
    "Problem": "المشكلة",
    "Handling": "المعالجة",
    "Start Work": "بدء العمل",
    "Mark Done": "إنهاء العمل",
    "Verify": "اعتماد",
    "Reset to New": "إعادة إلى جديد",
    "Confirmed On": "تاريخ التأكيد",
    "Started On": "تاريخ البدء",
    "Done On": "تاريخ الإنجاز",
    "Verified On": "تاريخ الاعتماد",
    "In Progress": "قيد التنفيذ",
    "Done": "منجز",
    "Verified": "معتمد",
    "Staff": "الموظفون",
    "Housekeeping": "التدبير الفندقي",
    "Inspection": "التفتيش",
    "Urgent": "عاجل",
    "High": "مرتفع",
    "Normal": "عادي",
    "Low": "منخفض",
    "Priority": "الأولوية",
    "Open": "مفتوحة",
    "Blocking a Room": "تحجب غرفة",
    "What the technician actually did.": "ما قام به الفني فعلياً.",
    "Describe the problem...": "صف المشكلة...",
    "What was done to fix it...": "ما تم عمله لإصلاحها...",
    "Report a maintenance problem": "الإبلاغ عن مشكلة صيانة",
    "Leave empty for common areas; use Location instead.": "اتركه فارغاً للمناطق العامة واستخدم حقل الموقع بدلاً منه.",
    "Where the problem is when it is not inside a room (lobby, kitchen, elevator...).": "مكان المشكلة عندما لا تكون داخل غرفة (البهو، المطبخ، المصعد...).",
    "The room cannot be sold while this request is open. Confirming the request takes the room out of order; verification returns it to service.": "لا يمكن بيع الغرفة أثناء فتح هذا الطلب؛ تأكيد الطلب يخرج الغرفة من الخدمة والاعتماد يعيدها.",
    # hotel_restricted_services
    "Restricted Services": "الخدمات المقيدة",
    "Restricted Services and Ceilings": "الخدمات المقيدة والسقوف",
    "Guest Service Restriction": "قيد خدمة النزيل",
    "Entity Service Ceiling": "سقف خدمات الجهة",
    "Entity Service Ceilings": "سقوف خدمات الجهات",
    "Service Ceilings": "سقوف الخدمات",
    "Service Category": "فئة الخدمة",
    "Service Restrictions": "قيود الخدمات",
    "Restriction": "القيد",
    "Blocked": "محظورة",
    "Allowed with Limit": "مسموحة بحد أقصى",
    "Daily Limit": "الحد اليومي",
    "Stay Limit": "حد الإقامة",
    "Daily Limit per Guest": "الحد اليومي لكل نزيل",
    "Reason / Note": "السبب / ملاحظة",
    "Leave empty to apply the ceiling to all services.": "اتركه فارغاً لتطبيق السقف على كل الخدمات.",
    "Define per-entity daily charge ceilings": "تحديد سقوف يومية للرسوم لكل جهة",
    "All Services": "كل الخدمات",
    # hotel_pos_room_charge
    "Charge to Room": "تحميل على الغرفة",
    "POS Order": "طلب نقطة البيع",
    "Room Charge": "رسوم على الغرفة",
    # hotel_reports
    "Daily Reports": "التقارير اليومية",
    "Daily Movement Report": "تقرير الحركة اليومية",
    "Hotel Daily Report Wizard": "معالج التقارير اليومية للفندق",
    "Arrivals": "الواصلون",
    "Departures": "المغادرون",
    "In-House Guests": "النزلاء المقيمون",
    "Security / Police List": "قائمة الأمن / الجوازات",
    "Business date the report covers.": "تاريخ العمل الذي يغطيه التقرير.",
    "Print": "طباعة",
    "Report Type": "نوع التقرير",
    "Birth Date": "تاريخ الميلاد",
    "Coming From": "قادم من",
    "Heading To": "متجه إلى",
    "Trip Number": "رقم الرحلة",
    "Total:": "الإجمالي:",
    "Property:": "الفندق:",
    "reservations": "حجوزات",
})

# Terms surfaced by generate_ar_po.py coverage report.
TRANSLATIONS.update({
    # hotel_base — groups, errors
    "Front Office Supervisor": "مشرف المكتب الأمامي",
    "Hotel Front Office": "المكتب الأمامي للفندق",
    "Hotel Housekeeping": "التدبير الفندقي",
    "Hotel Maintenance": "صيانة الفندق",
    "Hotel Management": "إدارة الفندق",
    "Manager": "المدير",
    "You cannot delete property %s because it has active or completed reservations.": "لا يمكن حذف المنشأة %s لوجود حجوزات نشطة أو مكتملة عليها.",
    "You cannot delete room %s because it has active reservations.": "لا يمكن حذف الغرفة %s لوجود حجوزات نشطة عليها.",
    "e.g. 101": "مثال: 101",
    # hotel_reservation
    "All Reservations": "كل الحجوزات",
    "Create the first reservation": "أنشئ أول حجز",
    "Drag on the timeline to book a room, or hit New.": "اسحب على الخط الزمني لحجز غرفة أو اضغط جديد.",
    "Room %(room)s is already booked between %(checkin)s and %(checkout)s.": "الغرفة %(room)s محجوزة بالفعل بين %(checkin)s و %(checkout)s.",
    "Room %(room)s is out of order or reserved for administration.": "الغرفة %(room)s خارج الخدمة أو محجوزة للإدارة.",
    "You can only delete draft or cancelled reservations.": "يمكن فقط حذف الحجوزات المسودة أو الملغاة.",
    # hotel_board
    "Front Desk Dashboard": "لوحة مكتب الاستقبال",
    "Reserved Rooms": "الغرف المحجوزة",
    "Vacant Clean": "شاغرة نظيفة",
    "Vacant Dirty": "شاغرة غير نظيفة",
    # hotel_folio
    "Define charge routing rules": "حدد قواعد توجيه الرسوم",
    "Hotel Folio": "فوليو الفندق",
    "No folios created yet": "لا توجد فوليوهات بعد",
    "You cannot delete a folio with posted or invoiced charges.": "لا يمكن حذف فوليو يحتوي على رسوم مرحلة أو مفوترة.",
    "You cannot delete a posted or invoiced folio line.": "لا يمكن حذف سطر فوليو مرحل أو مفوتر.",
    # hotel_rate
    "Define occupancy-based price bands": "حدد شرائح أسعار حسب الإشغال",
    "Define seasonal rate rules": "حدد قواعد أسعار موسمية",
    "This occupancy band overlaps with an existing band: %(overlap)s": "تتداخل هذه الشريحة مع شريحة موجودة: %(overlap)s",
    "This rate rule overlaps with an existing rate rule: %(overlap)s": "تتداخل قاعدة التسعير هذه مع قاعدة موجودة: %(overlap)s",
    # hotel_night_audit
    "Audit date %(audit_date)s does not match the property's current business date %(prop_date)s.": "تاريخ التدقيق %(audit_date)s لا يطابق تاريخ العمل الحالي للمنشأة %(prop_date)s.",
    "Start the first night audit": "ابدأ أول تدقيق ليلي",
    "You cannot delete a completed night audit record.": "لا يمكن حذف سجل تدقيق ليلي مكتمل.",
    # hotel_frontdesk_session
    "Front Desk Session": "جلسة مكتب الاستقبال",
    "Open a new front desk session": "افتح جلسة استقبال جديدة",
    "You cannot delete a closed front desk session.": "لا يمكن حذف جلسة استقبال مغلقة.",
    # hotel_housekeeping
    "Apply Changes": "تطبيق التغييرات",
    "Cleaned": "منظفة",
    "Cleaner": "عامل النظافة",
    "Cleaning": "جاري التنظيف",
    "Cleaning Status": "حالة التنظيف",
    "Discrepancy Lines": "سطور الفروقات",
    "Discrepancy Reconciliation": "مطابقة الفروقات",
    "Discrepancy?": "فرق؟",
    "Enter notes about room cleaning details, amenities replaced, or issues found...": "أدخل ملاحظات عن تفاصيل تنظيف الغرفة أو المستلزمات المستبدلة أو المشاكل المكتشفة...",
    "FO Status": "حالة المكتب الأمامي",
    "Housekeeping Cleaning Task": "مهمة تنظيف التدبير الفندقي",
    "Housekeeping Discrepancy Reconciliation": "مطابقة فروقات التدبير الفندقي",
    "Housekeeping Discrepancy Reconciliation Line": "سطر مطابقة فروقات التدبير الفندقي",
    "Housekeeping Discrepancy Reconciliation Wizard": "معالج مطابقة فروقات التدبير الفندقي",
    "Housekeeping Discrepancy Report": "تقرير فروقات التدبير الفندقي",
    "Housekeeping Physical Occupancy": "الإشغال الفعلي حسب التدبير الفندقي",
    "Housekeeping Task": "مهمة التدبير الفندقي",
    "Housekeeping Task Sequence": "تسلسل مهام التدبير الفندقي",
    "Housekeeping Tasks": "مهام التدبير الفندقي",
    "Mark Cleaned": "تحديد كمنظفة",
    "My Tasks": "مهامي",
    "No housekeeping tasks found.": "لا توجد مهام تدبير فندقي.",
    "Notes": "ملاحظات",
    "Room Details": "تفاصيل الغرفة",
    "Start Cleaning": "بدء التنظيف",
    "Started": "بدأت",
    "Task Reference": "مرجع المهمة",
    "Timings": "التوقيتات",
    "Wizard": "معالج",
    "You can only delete housekeeping tasks that are new or cancelled.": "يمكن فقط حذف مهام التنظيف الجديدة أو الملغاة.",
    "You can only mark a task as cleaned when it is in cleaning state.": "يمكن تحديد المهمة كمنظفة فقط عندما تكون قيد التنظيف.",
    "You can only start a new task.": "يمكن بدء المهام الجديدة فقط.",
    "You cannot cancel a task that is already cleaned.": "لا يمكن إلغاء مهمة تم تنظيفها بالفعل.",
    # hotel_maintenance
    "A request can only block a room when a room is set.": "لا يمكن للطلب حجب غرفة إلا عند تحديد غرفة.",
    "A verified request cannot be cancelled.": "لا يمكن إلغاء طلب معتمد.",
    "Only a manager can verify a maintenance request.": "يمكن للمدير فقط اعتماد طلب الصيانة.",
    "Only cancelled requests can be reset to new.": "يمكن فقط إعادة الطلبات الملغاة إلى جديد.",
    "Only confirmed requests can be started.": "يمكن فقط بدء الطلبات المؤكدة.",
    "Only done requests can be verified.": "يمكن فقط اعتماد الطلبات المنجزة.",
    "Only in-progress requests can be marked done.": "يمكن فقط إنهاء الطلبات قيد التنفيذ.",
    "Only new or cancelled maintenance requests can be deleted.": "يمكن فقط حذف طلبات الصيانة الجديدة أو الملغاة.",
    "Only new requests can be confirmed.": "يمكن فقط تأكيد الطلبات الجديدة.",
    # hotel_restricted_services
    "%(violation)s\nOverriding a service restriction requires the Front Office Supervisor role.": "%(violation)s\nتجاوز قيد الخدمة يتطلب صلاحية مشرف المكتب الأمامي.",
    "%(violation)s\nOverriding an entity ceiling requires the Front Office Supervisor role.": "%(violation)s\nتجاوز سقف الجهة يتطلب صلاحية مشرف المكتب الأمامي.",
    "Charges whose product belongs to this category (or a child of it) are restricted.": "تقيد الرسوم التي ينتمي منتجها إلى هذه الفئة أو إحدى فئاتها الفرعية.",
    "Daily ceiling of %(limit)s for entity %(entity)s (%(category)s) exceeded: %(billed)s billed today on this folio.": "تم تجاوز السقف اليومي %(limit)s للجهة %(entity)s (%(category)s): تمت فوترة %(billed)s اليوم على هذا الفوليو.",
    "Daily limit of %(limit)s for '%(category)s' exceeded (already charged %(charged)s, new charge %(amount)s).": "تم تجاوز الحد اليومي %(limit)s لفئة '%(category)s' (المحمل سابقاً %(charged)s، والرسم الجديد %(amount)s).",
    "Maximum billed to the entity per guest folio per calendar day. Zero means no daily limit.": "أقصى ما يفوتر على الجهة لكل فوليو نزيل في اليوم؛ الصفر يعني بلا حد يومي.",
    "Maximum charge total for the whole stay for this category. Zero means no stay limit.": "أقصى إجمالي رسوم لكامل الإقامة لهذه الفئة؛ الصفر يعني بلا حد للإقامة.",
    "Maximum charge total per calendar day for this category. Zero means no daily limit.": "أقصى إجمالي رسوم في اليوم لهذه الفئة؛ الصفر يعني بلا حد يومي.",
    "Service '%(category)s' is blocked for guest %(guest)s on this stay.": "الخدمة '%(category)s' محظورة على النزيل %(guest)s في هذه الإقامة.",
    "Service restriction overridden by %(user)s for %(product)s (%(amount)s). Reason: %(reason)s": "تم تجاوز قيد الخدمة بواسطة %(user)s للمنتج %(product)s (%(amount)s). السبب: %(reason)s",
    "Stay limit of %(limit)s for '%(category)s' exceeded (already charged %(charged)s, new charge %(amount)s).": "تم تجاوز حد الإقامة %(limit)s لفئة '%(category)s' (المحمل سابقاً %(charged)s، والرسم الجديد %(amount)s).",
    # hotel_pos_room_charge
    "%(guest)s has no in-house reservation. Room charges are only allowed for checked-in guests.": "لا يوجد حجز مقيم للنزيل %(guest)s؛ التحميل على الغرفة متاح فقط للنزلاء المسجلين دخولاً.",
    "POS order %(order)s charged to room (%(amount)s, %(count)s lines).": "تم تحميل طلب نقطة البيع %(order)s على الغرفة (%(amount)s، %(count)s سطور).",
    "POS order this charge came from, for the room-charge receipt and department reports.": "طلب نقطة البيع مصدر هذا الرسم، لإيصال تحميل الغرفة وتقارير الأقسام.",
    "Reservation %(reservation)s has no folio to charge.": "الحجز %(reservation)s لا يملك فوليو للتحميل عليه.",
    "Room charge must cover the whole order. Mixed payments (part cash, part room) are not supported.": "يجب أن يغطي التحميل على الغرفة كامل الطلب؛ الدفع المختلط (جزء نقدي وجزء على الغرفة) غير مدعوم.",
    "Select the hotel guest as the order's customer before charging to a room.": "اختر نزيل الفندق كعميل للطلب قبل التحميل على الغرفة.",
    "Settling with this method posts the order to the in-house guest's folio instead of collecting money at the POS. The order's customer must be a checked-in hotel guest.": "التسوية بهذه الطريقة ترحل الطلب إلى فوليو النزيل المقيم بدلاً من تحصيل النقود في نقطة البيع؛ ويجب أن يكون عميل الطلب نزيلاً مسجلاً دخوله.",
    # hotel_reports
    "Nights": "الليالي",
    "Reports": "التقارير",
})

# Production-readiness additions (property security, accounting, lifecycle,
# audit snapshots, guest services, and bilingual exports).
TRANSLATIONS.update({
    "Allowed Hotel Properties": "المنشآت الفندقية المسموح بها",
    "Default Hotel Property": "المنشأة الفندقية الافتراضية",
    "Food & Beverage": "الأغذية والمشروبات",
    "Hotel Accountant": "محاسب الفندق",
    "Hotel Accounting": "محاسبة الفندق",
    "House Use": "استخدام الفندق",
    "No Automatic Charge": "دون رسم تلقائي",
    "First Night": "الليلة الأولى",
    "Fixed Fee": "رسم ثابت",
    "Percentage of Stay": "نسبة من الإقامة",
    "Cancellation": "الإلغاء",
    "No-show": "عدم الحضور",
    "Stay Policies": "سياسات الإقامة",
    "Cancellation Grace (hours)": "مهلة الإلغاء (ساعات)",
    "No-show Grace (hours)": "مهلة عدم الحضور (ساعات)",
    "Cancellation Fee / Percentage": "رسم / نسبة الإلغاء",
    "No-show Fee / Percentage": "رسم / نسبة عدم الحضور",
    "Available Rooms": "الغرف المتاحة",
    "Amendments": "التعديلات",
    "Reservation Amendments": "تعديلات الحجوزات",
    "Approve and Apply": "اعتماد وتطبيق",
    "Room Move": "نقل الغرفة",
    "Extend Stay": "تمديد الإقامة",
    "Shorten Stay": "تقصير الإقامة",
    "Early Check-in": "دخول مبكر",
    "Late Checkout": "مغادرة متأخرة",
    "Day Use": "استخدام نهاري",
    "Manager Repricing": "إعادة التسعير بواسطة المدير",
    "Requested Rooms": "الغرف المطلوبة",
    "Rooming List": "قائمة توزيع الغرف",
    "Group Reservations": "حجوزات المجموعات",
    "Group / Block Reservations": "حجوزات المجموعات / الحصص",
    "Allocate Available Rooms": "تخصيص الغرف المتاحة",
    "Confirm Block": "تأكيد الحصة",
    "Applied": "مطبق",
    "New Values": "القيم الجديدة",
    "Audit Snapshot": "لقطة التدقيق",
    "Discount (%)": "الخصم (%)",
    "Untaxed": "قبل الضريبة",
    "Tax": "الضريبة",
    "Total": "الإجمالي",
    "Invoiced / Transferred": "المفوتر / المحول",
    "Manual FX": "سعر صرف يدوي",
    "Approve Manual FX Rate": "اعتماد سعر الصرف اليدوي",
    "Allocate Deposit / Advance": "تخصيص عربون / دفعة مقدمة",
    "Guest Deposit": "عربون النزيل",
    "Agency Advance": "دفعة جهة مقدمة",
    "Available Advance": "الرصيد المقدم المتاح",
    "Folio Settlement": "تسوية الفوليو",
    "Guest Refund": "استرداد للنزيل",
    "Cash Payout": "صرف نقدي",
    "Room-charge Clearing Account": "حساب مقاصة التحميل على الغرفة",
    "Room-charge Transfer Journal": "يومية تحويل التحميل على الغرفة",
    "Guest Deposit Journal": "يومية عربون النزيل",
    "Agency Advance Journal": "يومية دفعات الجهات المقدمة",
    "Cancellation Fee Product": "منتج رسم الإلغاء",
    "No-show Fee Product": "منتج رسم عدم الحضور",
    "Finance": "المالية",
    "Group Invoices": "فواتير المجموعة",
    "Create Group Invoice": "إنشاء فاتورة مجموعة",
    "Balance Override Reason": "سبب تجاوز الرصيد",
    "Payments": "الدفعات",
    "Posted Payments": "الدفعات المرحلة",
    "Reconciliation": "المطابقة",
    "Journal / Drawer": "اليومية / الدرج",
    "Journal / Currency Reconciliation": "مطابقة اليومية / العملة",
    "Reverse Audit": "عكس التدقيق",
    "Reverse Night Audit": "عكس التدقيق الليلي",
    "Reversed": "معكوس",
    "ADR": "متوسط سعر الغرفة",
    "RevPAR": "إيراد الغرفة المتاحة",
    "Room Board": "لوحة الغرف",
    "Retry": "إعادة المحاولة",
    "English": "الإنجليزية",
    "Export XLSX": "تصدير XLSX",
    "Debtors": "المدينون",
    "Cashier Close": "إقفال الصندوق",
    "Agency Advances": "دفعات الجهات المقدمة",
    "POS Room Charges": "مبيعات نقاط البيع على الغرف",
    "Consolidated Folio Statement": "كشف الفوليو الموحد",
    "Housekeeping Discrepancy": "فروقات التدبير الفندقي",
    "Hotel Operational Report": "التقرير التشغيلي للفندق",
    "Daily Movement Report Renderer": "عارض تقرير الحركة اليومية",
    "Hotel Report Wizard": "معالج تقارير الفندق",
    "Hotel reports in assigned properties": "تقارير الفندق في المنشآت المخصصة",
    "Property / الفندق:": "الفندق:",
    "Date / التاريخ:": "التاريخ:",
    "Total / الإجمالي:": "الإجمالي:",
    "Select a folio for the consolidated statement.": "اختر فوليو لكشف الحساب الموحد.",
    "System administrators: all hotel report wizards": "مديرو النظام: جميع معالجات تقارير الفندق",
    "Your hotel role cannot access this report type.": "دورك الفندقي لا يسمح بالوصول إلى هذا النوع من التقارير.",
    "Accounting": "القيد المحاسبي",
    "Payment / Advance": "دفعة / مبلغ مقدم",
    "Payments / Advances": "الدفعات / المبالغ المقدمة",
    "The payment and folio must use the same currency.": "يجب أن تستخدم الدفعة والفوليو العملة نفسها.",
    "Guest Services": "خدمات النزلاء",
    "Lost and Found": "المفقودات والموجودات",
    "Hotel Lost and Found Item": "سجل مفقودات وموجودات الفندق",
    "Do Not Disturb": "عدم الإزعاج",
    "Hotel Do Not Disturb Request": "طلب عدم إزعاج",
    "Wake-up Calls": "مكالمات الإيقاظ",
    "Hotel Wake-up Call": "مكالمة إيقاظ الفندق",
    "Found": "موجود",
    "Claimed": "تم التسليم",
    "Disposed": "تم الإتلاف",
    "Item Name": "اسم الصنف",
    "Storage Location": "مكان الحفظ",
    "Claimed By": "تم التسليم إلى",
    "Mark Claimed": "تحديد كمسلم",
    "Dispose": "إتلاف",
    "DND requests in assigned properties": "طلبات عدم الإزعاج في المنشآت المخصصة",
    "Wake-up calls in assigned properties": "مكالمات الإيقاظ في المنشآت المخصصة",
    "Lost and found in assigned properties": "المفقودات والموجودات في المنشآت المخصصة",
    "Scheduled": "مجدولة",
    "Completed": "مكتملة",
    "Missed": "فائتة",
    "Scheduled At": "موعد التنفيذ",
    "Assigned User": "الموظف المكلف",
    "Completion Note": "ملاحظة الإتمام",
    "Completed At": "وقت الإتمام",
    "End DND": "إنهاء عدم الإزعاج",
})

header_template = """# Translation of Odoo Server.
# This file contains the translation of the following module:
# 	* {module_name}
#
msgid ""
msgstr ""
"Project-Id-Version: Odoo Server 19.0\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: 2026-07-11 12:00+0000\\n"
"PO-Revision-Date: 2026-07-11 12:00+0000\\n"
"Last-Translator: Antigravity <antigravity@gemini.google>\\n"
"Language-Team: Arabic (https://www.transifex.com/odoo/teams/41243/ar/)\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: ar\\n"
"Plural-Forms: nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5;\\n"

"""

def parse_po_file(filepath):
    """
    Parses a PO file and returns a list of dictionaries, where each dictionary
    represents a translation block: comment, occurrences, msgid, msgstr.
    """
    entries = []
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Split into entries by double newlines
    raw_entries = content.split("\n\n")
    for raw in raw_entries:
        raw = raw.strip()
        if not raw:
            continue
        
        # Skip header
        if "msgid \"\"" in raw and "msgstr \"\"" in raw:
            continue
            
        entry = {"comment": "", "occurrences": [], "msgid": "", "msgstr": ""}
        msgid_lines = []
        msgstr_lines = []
        in_msgid = False
        in_msgstr = False
        
        lines = raw.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("#."):
                entry["comment"] = line[2:].strip()
            elif line.startswith("#:"):
                entry["occurrences"].append(line[2:].strip())
            elif line.startswith("msgid"):
                in_msgid = True
                in_msgstr = False
                val = line.split("msgid", 1)[1].strip()
                if val.startswith('"') and val.endswith('"'):
                    msgid_lines.append(val[1:-1])
            elif line.startswith("msgstr"):
                in_msgid = False
                in_msgstr = True
                val = line.split("msgstr", 1)[1].strip()
                if val.startswith('"') and val.endswith('"'):
                    msgstr_lines.append(val[1:-1])
            elif line.startswith('"') and line.endswith('"'):
                if in_msgid:
                    msgid_lines.append(line[1:-1])
                elif in_msgstr:
                    msgstr_lines.append(line[1:-1])
                    
        entry["msgid"] = "".join(msgid_lines)
        entry["msgstr"] = "".join(msgstr_lines)
        
        # Only add entries that have occurrences
        if entry["msgid"] and entry["occurrences"]:
            entries.append(entry)
            
    return entries

def main():
    po_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ar.po"
    if not os.path.exists(po_path):
        print(f"Error: {po_path} does not exist. Please run Odoo translation export first!")
        return

    print(f"Reading and parsing {po_path}...")
    entries = parse_po_file(po_path)
    print(f"Parsed {len(entries)} translation records.")

    # Group entries by module name
    module_entries = {}
    for entry in entries:
        module = ""
        # Match module name from occurrences or comment
        if entry["comment"] and entry["comment"].startswith("module:"):
            module = entry["comment"].split("module:", 1)[1].strip()
        else:
            # Try to match from occurrences (e.g. model:ir.ui.menu,name:hotel_base.menu)
            for occurrence in entry["occurrences"]:
                # Matches model:something:module.xmlid
                match = re.match(r'.*:([\w_]+)\.([^ ]+)', occurrence)
                if match:
                    module = match.group(1)
                    break
        
        # If it doesn't match any hotel module, skip
        if not module or not module.startswith("hotel_"):
            continue
            
        if module not in module_entries:
            module_entries[module] = []
        module_entries[module].append(entry)

    # Write translated entries to each module's ar.po
    user_src_dir = "/home/odoo/src/user"
    if not os.path.exists(user_src_dir):
        # Fallback to local workspace if run locally
        user_src_dir = os.path.dirname(os.path.abspath(__file__))

    for module, entries in module_entries.items():
        module_dir = os.path.join(user_src_dir, module)
        if not os.path.isdir(module_dir):
            print(f"Warning: Module directory {module_dir} does not exist. Skipping.")
            continue
            
        po_output_dir = os.path.join(module_dir, "i18n")
        os.makedirs(po_output_dir, exist_ok=True)
        po_output_path = os.path.join(po_output_dir, "ar.po")

        po_lines = []
        untranslated = []
        for entry in entries:
            msgid = entry["msgid"]
            # PO reads an entry's msgid with \" and \\ unescaped; the
            # dictionary stores plain text, so unescape before lookup.
            plain_msgid = (
                msgid.replace('\\"', '"').replace("\\\\", "\\")
            )
            # Empty msgstr = untranslated (falls back to English);
            # never write the English source as a fake translation.
            msgstr = TRANSLATIONS.get(plain_msgid, "")
            if not msgstr:
                untranslated.append(plain_msgid)

            # format the record block
            block = []
            block.append(f"#. module: {module}")
            for occ in entry["occurrences"]:
                block.append(f"#: {occ}")
            block.append(f'msgid "{msgid}"')
            block.append(f'msgstr "{po_escape(msgstr)}"')
            po_lines.append("\n".join(block))

        if untranslated:
            print(f"  [{module}] {len(untranslated)} untranslated terms:")
            for term in untranslated:
                print(f"    - {term}")

        with open(po_output_path, "w", encoding="utf-8") as f:
            f.write(header_template.format(module_name=module))
            f.write("\n\n".join(po_lines))
            f.write("\n")
            
        print(f"Generated clean translation file: {po_output_path} with {len(entries)} occurrences.")

if __name__ == "__main__":
    main()
