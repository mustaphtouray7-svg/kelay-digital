"use strict";

const menuButton = document.querySelector(".menu-toggle");
const navigation = document.querySelector("#primary-nav");
const languageButton = document.querySelector("#language-toggle");
let currentLanguage = "en";

const translations = {
  en: {
    demo:"SCHOOL WEBSITE SAMPLE — PREVIEW VERSION",demoNote:"Student portal is a visual prototype; it does not save information.",shortName:"LALO KANTEH INSTITUTE",locationShort:"TABOKOTO · THE GAMBIA",
    navAbout:"About",navStudies:"Islamic Studies",navAdmissions:"Admissions",navPortal:"Student Portal",navContact:"Contact",
    heroEyebrow:"ISLAMIC LEARNING · KNOWLEDGE · CHARACTER",heroTitle:"ALH. LALO KANTEH\nISLAMIC INSTITUTE",heroLead:"A learning community dedicated to Islamic education, good character, and the pursuit of beneficial knowledge in Tabokoto, The Gambia.",exploreStudies:"Explore Islamic Studies",openPortal:"Student Portal",heroProof:"Knowledge with purpose",heroProofSmall:"Rooted in faith, learning, and respect.",welcome:"WELCOME",
    aboutEyebrow:"ABOUT THE INSTITUTE",aboutTitle:"A place to learn.\nA foundation for life.",aboutLead:"Alh. Lalo Kanteh Islamic Institute is based in Tabokoto, The Gambia, and focuses on Islamic learning and the development of students' character.",aboutText:"This website sample is prepared for the institute. The school can add its approved history, leadership message, learning approach, and official photographs before launch.",askSchool:"Contact the institute",visualTitle:"Faith and knowledge",visualSubtitle:"Learning with purpose and good character.",ourStory:"/ OUR INSTITUTE",
    studiesEyebrow:"LEARNING AT THE INSTITUTE",studiesTitle:"Islamic knowledge.\nStrong character.",studiesLead:"The institute's focus is Islamic education. The subjects below are examples to confirm with the school before the website goes live.",studyOneLabel:"01 / QUR'AN",studyOneTitle:"Qur'an studies",studyOneText:"A sample subject card for Qur'an learning and recitation, subject to confirmation.",studyTwoLabel:"02 / ISLAMIC STUDIES",studyTwoTitle:"Islamic knowledge",studyTwoText:"A sample section for Islamic subjects taught at the institute, to be edited to match the real curriculum.",studyThreeLabel:"03 / ARABIC",studyThreeTitle:"Arabic language",studyThreeText:"A sample subject card for Arabic language learning, pending confirmation by the school.",subjectNote:"These subject cards are examples only. They are not a confirmed list of the institute's curriculum.",
    admissionsEyebrow:"JOIN OUR LEARNING COMMUNITY",admissionsTitle:"Begin your\nlearning journey.",admissionsText:"Families can contact the institute to ask about admission, class levels, required documents, and the current school calendar.",admissionsButton:"Ask about admissions",stepOneTitle:"Contact the institute",stepOneText:"Ask about current admissions and class levels.",stepTwoTitle:"Confirm requirements",stepTwoText:"Check documents and any school-specific guidance.",stepThreeTitle:"Speak with the school",stepThreeText:"The school will explain the next steps.",admissionsNote:"Admissions guidance must be confirmed by the institute.",
    portalEyebrow:"STUDENT AREA",portalTitle:"Student portal\nsample sign-up.",portalLead:"This preview shows the details a future student portal could request. The school must connect it to a secure system before real students use it.",privacyTitle:"Demo privacy notice",privacyText:"Do not enter a real password or private student details here. This form does not create an account or send or save information.",portalFormTitle:"STUDENT REGISTRATION PREVIEW",fullNameLabel:"Full name",fullNamePlaceholder:"Enter your full name",surnameLabel:"Surname",surnamePlaceholder:"Enter your surname",phoneLabel:"Phone number",phonePlaceholder:"Enter phone number",addressLabel:"Address / area",addressPlaceholder:"Enter your town or address",passwordLabel:"Create a password (demo only)",passwordPlaceholder:"At least 8 characters",registerButton:"Preview registration",portalFootnote:"Prototype only. Nothing is transmitted or stored; no account is created.",
    contactEyebrow:"GET IN TOUCH",contactTitle:"Questions about\nthe institute?",contactText:"For official school information, please contact Alh. Lalo Kanteh Islamic Institute using the email address below.",emailLabel:"Email the institute",locationFull:"Tabokoto, The Gambia",contactCardText:"Tabokoto, The Gambia",sendEmail:"Send an email",websiteBy:"Website concept by",backTop:"Back to top ↑",footerName:"Alh. Lalo Kanteh Islamic Institute",footerTagline:"A sample website prepared for school review.",
    studentSuccess:"This is only a preview. No account was created and no information was sent or saved. Please do not enter real student details or passwords."
  },
  ar: {
    demo:"نموذج تجريبي لموقع المدرسة",demoNote:"بوابة الطلاب نموذج للعرض فقط ولا تحفظ المعلومات.",shortName:"معهد لالو كانتي الإسلامي",locationShort:"تابوكوتو · غامبيا",
    navAbout:"عن المعهد",navStudies:"الدراسات الإسلامية",navAdmissions:"القبول",navPortal:"بوابة الطلاب",navContact:"اتصل بنا",
    heroEyebrow:"التعلم الإسلامي · المعرفة · الأخلاق",heroTitle:"معهد الحاج لالو كانتي الإسلامي",heroLead:"مجتمع تعليمي يهتم بالتعليم الإسلامي وحسن الأخلاق وطلب العلم النافع في تابوكوتو، غامبيا.",exploreStudies:"تعرّف على الدراسات الإسلامية",openPortal:"بوابة الطلاب",heroProof:"العلم له هدف",heroProofSmall:"إيمان وعلم واحترام.",welcome:"أهلاً وسهلاً",
    aboutEyebrow:"عن المعهد",aboutTitle:"مكان للتعلم.\nوأساس للحياة.",aboutLead:"يقع معهد الحاج لالو كانتي الإسلامي في تابوكوتو بغانبيا، ويركز على التعلم الإسلامي وتنمية أخلاق الطلاب.",aboutText:"أُعدّ هذا النموذج لموقع المعهد. ويمكن إضافة تاريخه المعتمد وكلمة الإدارة وطريقة التعليم والصور الرسمية قبل نشر الموقع.",askSchool:"تواصل مع المعهد",visualTitle:"الإيمان والعلم",visualSubtitle:"تعلم هادف وأخلاق حسنة.",ourStory:"/ معهدنا",
    studiesEyebrow:"التعلم في المعهد",studiesTitle:"علم إسلامي.\nوأخلاق راسخة.",studiesLead:"يركز المعهد على التعليم الإسلامي. والمواد التالية أمثلة تحتاج إلى تأكيد من إدارة المعهد قبل نشر الموقع.",studyOneLabel:"٠١ / القرآن الكريم",studyOneTitle:"دراسة القرآن الكريم",studyOneText:"قسم تجريبي لتعلم القرآن وتلاوته، ويحتاج إلى تأكيد المعهد.",studyTwoLabel:"٠٢ / الدراسات الإسلامية",studyTwoTitle:"العلوم الإسلامية",studyTwoText:"قسم تجريبي للمواد الإسلامية التي يدرسها المعهد، ويُعدّل حسب المنهج الفعلي.",studyThreeLabel:"٠٣ / اللغة العربية",studyThreeTitle:"اللغة العربية",studyThreeText:"قسم تجريبي لتعلم اللغة العربية، ويحتاج إلى تأكيد المدرسة.",subjectNote:"هذه المواد أمثلة فقط وليست قائمة مؤكدة بمنهج المعهد.",
    admissionsEyebrow:"انضم إلى مجتمعنا التعليمي",admissionsTitle:"ابدأ رحلة\nالتعلم.",admissionsText:"يمكن للأسر التواصل مع المعهد للاستفسار عن القبول والمراحل الدراسية والوثائق المطلوبة والتقويم المدرسي الحالي.",admissionsButton:"استفسر عن القبول",stepOneTitle:"تواصل مع المعهد",stepOneText:"استفسر عن القبول والمراحل الدراسية المتاحة.",stepTwoTitle:"تأكد من المتطلبات",stepTwoText:"تحقق من الوثائق والتعليمات الخاصة بالمعهد.",stepThreeTitle:"تحدث مع الإدارة",stepThreeText:"ستوضح المدرسة الخطوات التالية.",admissionsNote:"يجب تأكيد معلومات القبول من إدارة المعهد.",
    portalEyebrow:"منطقة الطلاب",portalTitle:"بوابة الطلاب\nنموذج تسجيل.",portalLead:"يعرض هذا النموذج البيانات التي قد تطلبها بوابة الطلاب مستقبلاً. يجب ربطها بنظام آمن قبل استخدامها من الطلاب الحقيقيين.",privacyTitle:"تنبيه الخصوصية للنموذج",privacyText:"لا تدخل كلمة مرور حقيقية أو بيانات خاصة بالطلاب هنا. هذا النموذج لا ينشئ حساباً ولا يرسل المعلومات أو يحفظها.",portalFormTitle:"معاينة تسجيل الطلاب",fullNameLabel:"الاسم الكامل",fullNamePlaceholder:"اكتب اسمك الكامل",surnameLabel:"اسم العائلة",surnamePlaceholder:"اكتب اسم العائلة",phoneLabel:"رقم الهاتف",phonePlaceholder:"اكتب رقم الهاتف",addressLabel:"العنوان / المنطقة",addressPlaceholder:"اكتب المدينة أو العنوان",passwordLabel:"إنشاء كلمة مرور (للتجربة فقط)",passwordPlaceholder:"ثمانية أحرف على الأقل",registerButton:"معاينة التسجيل",portalFootnote:"نموذج تجريبي فقط. لا يتم إرسال أو حفظ أي شيء ولا يتم إنشاء حساب.",
    contactEyebrow:"تواصل معنا",contactTitle:"هل لديك أسئلة\nعن المعهد؟",contactText:"للحصول على معلومات رسمية، يرجى التواصل مع معهد الحاج لالو كانتي الإسلامي عبر البريد الإلكتروني أدناه.",emailLabel:"البريد الإلكتروني للمعهد",locationFull:"تابوكوتو، غامبيا",contactCardText:"تابوكوتو، غامبيا",sendEmail:"إرسال بريد إلكتروني",websiteBy:"تصميم الموقع بواسطة",backTop:"العودة إلى الأعلى ↑",footerName:"معهد الحاج لالو كانتي الإسلامي",footerTagline:"نموذج موقع لمراجعة إدارة المعهد.",
    studentSuccess:"هذه معاينة فقط. لم يتم إنشاء حساب ولم تُرسل أو تُحفظ أي معلومات. يُرجى عدم إدخال بيانات الطلاب الحقيقية أو كلمات المرور."
  }
};

function applyLanguage(language) {
  currentLanguage = language;
  document.documentElement.lang = language;
  document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const key = element.dataset.i18n;
    if (translations[language][key]) element.textContent = translations[language][key];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
    const key = element.dataset.i18nPlaceholder;
    if (translations[language][key]) element.placeholder = translations[language][key];
  });
  if (languageButton) {
    languageButton.textContent = language === "en" ? "العربية" : "English";
    languageButton.setAttribute("aria-label", language === "en" ? "Switch to Arabic" : "التبديل إلى الإنجليزية");
  }
  document.title = language === "ar"
    ? "معهد الحاج لالو كانتي الإسلامي بتبوكتو"
    : "Alh. Lalo Kanteh Islamic Institute | Tabokoto";
}

if (languageButton) {
  languageButton.addEventListener("click", () => applyLanguage(currentLanguage === "en" ? "ar" : "en"));
}

function closeMenu() {
  if (!menuButton || !navigation) return;
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Open navigation");
  navigation.classList.remove("is-open");
}

if (menuButton && navigation) {
  menuButton.addEventListener("click", () => {
    const expanded = menuButton.getAttribute("aria-expanded") === "true";
    menuButton.setAttribute("aria-expanded", String(!expanded));
    menuButton.setAttribute("aria-label", expanded ? "Open navigation" : "Close navigation");
    navigation.classList.toggle("is-open", !expanded);
  });
  navigation.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
      menuButton.focus();
    }
  });
}

const year = document.querySelector("#year");
if (year) year.textContent = new Date().getFullYear();

const studentForm = document.querySelector("#student-form");
const studentStatus = document.querySelector("#student-status");
if (studentForm && studentStatus) {
  studentForm.addEventListener("submit", (event) => {
    event.preventDefault();
    studentStatus.textContent = translations[currentLanguage].studentSuccess;
    studentForm.reset();
  });
}

applyLanguage("en");