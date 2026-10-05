"use strict";

const CONTACT_DETAILS = {
  email: "",
  whatsappNumber: ""
};

const menuButton = document.querySelector(".menu-toggle");
const navigation = document.querySelector("#primary-nav");

function closeMenu() {
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Open navigation");
  navigation.classList.remove("is-open");
}

menuButton.addEventListener("click", () => {
  const isExpanded = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!isExpanded));
  menuButton.setAttribute("aria-label", isExpanded ? "Open navigation" : "Close navigation");
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

document.querySelectorAll('[data-contact="email"]').forEach((link) => {
  if (CONTACT_DETAILS.email) {
    link.href = `mailto:${CONTACT_DETAILS.email}`;
    link.textContent = link.classList.contains("button") ? "Email Kelay Digital" : CONTACT_DETAILS.email;
  } else {
    link.removeAttribute("href");
    link.classList.add("is-placeholder");
    if (link.classList.contains("button")) {
      link.setAttribute("aria-disabled", "true");
      link.addEventListener("click", (event) => event.preventDefault());
    } else {
      link.textContent = "Email contact details coming soon";
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
  }
});

document.querySelector("#year").textContent = new Date().getFullYear();
