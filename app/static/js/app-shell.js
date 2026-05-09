(() => {
  const path = window.location.pathname;

  const links = document.querySelectorAll(".navLink");
  links.forEach((link) => {
    const href = link.getAttribute("href");
    if (!href) return;
    const isActive = href === "/" ? path === "/" : path.startsWith(href);
    link.classList.toggle("active", isActive);
  });

  const navToggle = document.getElementById("navToggle");
  const navLinks = document.querySelector(".navLinks");

  const closeMenu = () => {
    document.body.classList.remove("menu-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "false");
  };

  if (navToggle && navLinks) {
    navToggle.setAttribute("aria-expanded", "false");
    navToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = document.body.classList.toggle("menu-open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    navLinks.addEventListener("click", () => closeMenu());

    document.addEventListener("click", (event) => {
      if (!document.body.classList.contains("menu-open")) return;
      if (navLinks.contains(event.target) || navToggle.contains(event.target)) return;
      closeMenu();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu();
    });
  }

  let toastStack = document.getElementById("toastStack");
  if (!toastStack) {
    toastStack = document.createElement("div");
    toastStack.id = "toastStack";
    toastStack.className = "toastStack";
    document.body.appendChild(toastStack);
  }

  function toast(message, level = "info", timeoutMs = 2600) {
    const item = document.createElement("div");
    item.className = `toastItem ${level}`;
    item.textContent = message;
    toastStack.appendChild(item);
    window.setTimeout(() => {
      item.remove();
    }, timeoutMs);
  }

  window.AppShell = Object.assign(window.AppShell || {}, { toast });
})();
