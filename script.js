"use strict";

const CONTACT_DETAILS = {
  email: "mustaphtouray7@gmail.com",
  whatsappNumber: "589066"
};

const menuButton = document.querySelector(".menu-toggle");
const navigation = document.querySelector("#primary-nav");

function closeMenu() {
  if (!menuButton || !navigation) return;
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Open navigation");
  navigation.classList.remove("is-open");
}

if (menuButton && navigation) {
  menuButton.addEventListener("click", () => {
    const isExpanded = menuButton.getAttribute("aria-expanded") === "true";
    menuButton.setAttribute("aria-expanded", String(!isExpanded));
    menuButton.setAttribute(
      "aria-label",
      isExpanded ? "Open navigation" : "Close navigation"
    );
    navigation.classList.toggle("is-open", !isExpanded);
  });

  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) closeMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && navigation.classList.contains("is-open")) {
      closeMenu();
      menuButton.focus();
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 640 && navigation.classList.contains("is-open")) {
      closeMenu();
    }
  });
}

document.querySelectorAll('[data-contact="email"]').forEach((link) => {
  if (CONTACT_DETAILS.email) {
    link.href = `mailto:${CONTACT_DETAILS.email}`;
    if (!link.classList.contains("button")) {
      link.textContent = CONTACT_DETAILS.email;
    }
  } else {
    link.removeAttribute("href");
    link.classList.add("is-placeholder");
    link.setAttribute("aria-disabled", "true");
    link.setAttribute("title", "Business email will be added soon");
    if (link.classList.contains("button")) {
      link.addEventListener("click", (event) => event.preventDefault());
    } else {
      link.textContent = "Business email coming soon";
    }
  }
});

document.querySelectorAll('[data-contact="whatsapp"]').forEach((link) => {
  if (CONTACT_DETAILS.whatsappNumber) {
    const number = CONTACT_DETAILS.whatsappNumber.replace(/\D/g, "");
    link.href = `https://wa.me/${number}`;
    link.textContent = "Chat with Kelay Digital";
  } else {
    link.removeAttribute("href");
    link.classList.add("is-placeholder");
    link.setAttribute("aria-disabled", "true");
    link.setAttribute("title", "WhatsApp number will be added soon");
    link.textContent = "WhatsApp contact coming soon";
  }
});

const yearElement = document.querySelector("#year");
if (yearElement) {
  yearElement.textContent = new Date().getFullYear();
}
