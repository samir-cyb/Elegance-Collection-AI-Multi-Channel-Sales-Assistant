gsap.registerPlugin(ScrollTrigger);

document.addEventListener("DOMContentLoaded", () => {
  // Hero entrance
  gsap.from(".hero h1", { y: 40, opacity: 0, duration: 1, ease: "power3.out" });
  gsap.from(".hero p", { y: 30, opacity: 0, duration: 1, delay: 0.2, ease: "power3.out" });
  gsap.from(".hero .cta-row", { y: 20, opacity: 0, duration: 1, delay: 0.4, ease: "power3.out" });

  // Scrollytelling story panels (Home page)
  gsap.utils.toArray(".story-panel").forEach((panel, i) => {
    const txt = panel.querySelector(".txt");
    const visual = panel.querySelector(".visual");
    gsap.from(txt, {
      x: i % 2 === 0 ? -60 : 60,
      opacity: 0,
      duration: 1,
      scrollTrigger: { trigger: panel, start: "top 75%" },
    });
    gsap.from(visual, {
      scale: 0.85,
      opacity: 0,
      duration: 1,
      scrollTrigger: { trigger: panel, start: "top 75%" },
    });
  });

  // Feature card stagger reveal
  gsap.from(".feature-card", {
    y: 40,
    opacity: 0,
    duration: 0.8,
    stagger: 0.12,
    scrollTrigger: { trigger: ".feature-grid", start: "top 85%" },
  });

  // Product grid reveal (Product page)
  gsap.from(".product-card", {
    y: 50,
    opacity: 0,
    duration: 0.7,
    stagger: 0.08,
    scrollTrigger: { trigger: ".product-grid", start: "top 90%" },
  });

  // Chatbot widget entrance
  gsap.from(".chat-wrap", { y: 40, opacity: 0, duration: 0.9, ease: "power3.out" });
});
