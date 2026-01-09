// frontend/web-import.js
window.addEventListener("DOMContentLoaded", function () {
  console.log("CaseLib web-import.js DOMContentLoaded");

  const urlInput = document.getElementById("import-url-input");
  const parseBtn = document.getElementById("import-parse-btn");
  const previewSection = document.getElementById("import-preview-section");
  const supportedList = document.getElementById("supported-sites-list");

  let lastParsed = null;
  let currentTaskId = null;
  let statusTimer = null;

  function clearStatusTimer() {
    if (statusTimer) {
      clearInterval(statusTimer);
      statusTimer = null;
    }
  }

  // ===== 手动写死当前支持的网站 =====
  function fillSupportedSitesStatic() {
    if (!supportedList) return;
    supportedList.innerHTML = "";

    const sites = [
      "ArchDaily（archdaily.cn / archdaily.com）",
      "谷德（gooood.cn）",
      "微信公众号"
    ];

    sites.forEach((txt) => {
      const li = document.createElement("li");
      li.textContent = txt;
      supportedList.appendChild(li);
    });
  }

  function renderEmptyPreview() {
    if (!previewSection) return;
    previewSection.classList.add("web-import-preview-section--empty");
    previewSection.innerHTML =
      '<p class="center-hint">解析成功后将在这里预览项目信息和图片。</p>';
  }

  // 正在解析的状态
  function renderLoadingPreview(url) {
    if (!previewSection) return;
    previewSection.classList.remove("web-import-preview-section--empty");
    previewSection.innerHTML = [
      '<div class="web-import-preview-card">',
      '  <div class="web-import-preview-left">',
      '    <div class="web-import-cover-placeholder">正在解析项目…</div>',
      "  </div>",
      '  <div class="web-import-preview-right">',
      '    <h2 class="web-import-title">正在解析链接</h2>',
      '    <div class="web-import-meta-list">',
      '      <div class="web-import-meta-item"><span class="label">项目链接：</span><span class="value">' +
        (url
          ? '<span style="word-break:break-all;">' + url + "</span>"
          : "（空）") +
        "</span></div>",
      '      <div class="web-import-meta-item"><span class="label">状态：</span><span class="value">请稍候，正在抓取页面并分析图片…</span></div>',
      "    </div>",
      "  </div>",
      "</div>",
    ].join("\n");
  }

  // 解析失败时的预览区域提示
  function renderErrorPreview(message) {
    if (!previewSection) return;
    previewSection.classList.remove("web-import-preview-section--empty");
    previewSection.innerHTML = [
      '<div class="web-import-preview-card">',
      '  <div class="web-import-preview-left">',
      '    <div class="web-import-cover-placeholder">解析失败</div>',
      "  </div>",
      '  <div class="web-import-preview-right">',
      '    <h2 class="web-import-title">解析失败</h2>',
      '    <div class="web-import-meta-list">',
      '      <div class="web-import-meta-item"><span class="label">原因：</span><span class="value" style="color:#b91c1c;">' +
        (message || "未知错误") +
        "</span></div>",
      "    </div>",
      "  </div>",
      "</div>",
    ].join("\n");
  }

  function renderParsedPreview(parsed) {
    if (!previewSection) return;
    lastParsed = parsed;
    currentTaskId = null;
    clearStatusTimer();

    const firstImage =
      parsed.image_urls && parsed.image_urls.length > 0
        ? parsed.image_urls[0]
        : null;

    const architect =
      parsed.meta && typeof parsed.meta.architect === "string"
        ? parsed.meta.architect
        : parsed.meta && parsed.meta.architect
        ? String(parsed.meta.architect)
        : parsed.meta && parsed.meta.Architects
        ? String(parsed.meta.Architects)
        : "";

    const location =
      parsed.meta && (parsed.meta.location || parsed.meta.location_city)
        ? parsed.meta.location || parsed.meta.location_city
        : "";

    const category =
      parsed.meta && parsed.meta.category ? String(parsed.meta.category) : "";

    const year =
      parsed.meta && parsed.meta.year ? String(parsed.meta.year) : "";

    const description =
      parsed.meta && parsed.meta.description
        ? String(parsed.meta.description)
        : "";

    previewSection.classList.remove("web-import-preview-section--empty");

    const html = [
      '<div class="web-import-preview-card">',
      '  <div class="web-import-preview-left">',
      firstImage
        ? '    <div class="web-import-cover-wrap"><img src="' +
          firstImage +
          '" alt="封面预览" /></div>'
        : '    <div class="web-import-cover-placeholder">暂无可预览图片</div>',
      "  </div>",
      '  <div class="web-import-preview-right">',
      '    <h2 class="web-import-title">' + (parsed.title || "(未命名项目)") + "</h2>",
      '    <div class="web-import-meta-list">',
      '      <div class="web-import-meta-item"><span class="label">来源网站：</span><span class="value">' +
        (parsed.site || "") +
        "</span></div>",
      '      <div class="web-import-meta-item"><span class="label">原始链接：</span><span class="value"><a href="' +
        parsed.url +
        '" target="_blank" rel="noopener noreferrer">' +
        parsed.url +
        "</a></span></div>",
      architect
        ? '      <div class="web-import-meta-item"><span class="label">建筑师：</span><span class="value">' +
          architect +
          "</span></div>"
        : "",
      location
        ? '      <div class="web-import-meta-item"><span class="label">地点：</span><span class="value">' +
          location +
          "</span></div>"
        : "",
      category
        ? '      <div class="web-import-meta-item"><span class="label">类型：</span><span class="value">' +
          category +
          "</span></div>"
        : "",
      year
        ? '      <div class="web-import-meta-item"><span class="label">年份：</span><span class="value">' +
          year +
          "</span></div>"
        : "",
      "    </div>",
      description
        ? '    <div class="web-import-description"><div class="label">简介：</div><div class="value">' +
          description
            .split("\n")
            .map((line) => "<p>" + line + "</p>")
            .join("") +
          "</div></div>"
        : "",
      '    <div class="web-import-folder-row">',
      '      <label for="import-folder-input">目标文件夹名：</label>',
      '      <input id="import-folder-input" type="text" value="' +
        (parsed.suggested_folder || "") +
        '" />',
      "    </div>",
      '    <div class="web-import-actions">',
      '      <button id="import-start-btn" type="button">开始导入</button>',
      '      <div id="import-status-text" class="web-import-status-text"></div>',
      "    </div>",
      "  </div>",
      "</div>",
    ].join("\n");

    previewSection.innerHTML = html;

    const startBtn = document.getElementById("import-start-btn");
    const folderInput = document.getElementById("import-folder-input");
    const statusText = document.getElementById("import-status-text");

    function setStatus(text) {
      if (statusText) {
        statusText.textContent = text || "";
      }
    }

    async function checkStatusOnce(taskId) {
      try {
        const res = await fetch("/api/web-import/status/" + taskId);
        if (!res.ok) throw new Error("status=" + res.status);
        const data = await res.json();
        currentTaskId = data.task_id;
        const p = data.progress != null ? Math.round(data.progress * 100) : 0;
        let line = "";
        if (data.status === "running") {
          line = "正在导入：" + p + "% – " + (data.message || "");
        } else if (data.status === "pending") {
          line = "任务排队中…";
        } else if (data.status === "done") {
          line = "导入完成：" + (data.message || "");
          clearStatusTimer();
        } else if (data.status === "error") {
          line = "导入失败：" + (data.message || "");
          clearStatusTimer();
        } else {
          line = data.message || "";
        }
        setStatus(line);
      } catch (e) {
        console.warn("获取任务状态失败：", e);
        setStatus("获取任务状态失败");
        clearStatusTimer();
      }
    }

    async function startImport() {
      if (!lastParsed) return;
      const folderName = folderInput ? folderInput.value.trim() : "";
      if (!folderName) {
        alert("请先填写目标文件夹名");
        return;
      }
      setStatus("正在创建导入任务…");
      clearStatusTimer();
      currentTaskId = null;

      try {
        const res = await fetch("/api/web-import/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: lastParsed.url,
            folder_name: folderName,
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => null);
          const msg =
            (errData && errData.detail) ||
            "启动导入失败（status=" + res.status + "）";
          setStatus(msg);
          alert(msg);
          return;
        }
        const data = await res.json();
        currentTaskId = data.task_id;
        setStatus("导入任务已启动，正在后台运行…");

        statusTimer = setInterval(() => {
          if (currentTaskId) {
            checkStatusOnce(currentTaskId);
          }
        }, 2000);
        checkStatusOnce(currentTaskId);
      } catch (e) {
        console.error("启动导入失败：", e);
        setStatus("启动导入失败");
      }
    }

    if (startBtn) {
      startBtn.addEventListener("click", startImport);
    }
  }

  async function handleParseClick() {
    if (!urlInput) return;
    const url = urlInput.value.trim();
    console.log("解析按钮点击，URL =", url);
    if (!url) {
      alert("请先粘贴项目链接");
      return;
    }

    // 显示“正在解析”状态，并禁用按钮
    renderLoadingPreview(url);
    if (parseBtn) {
      parseBtn.disabled = true;
      parseBtn.textContent = "解析中…";
    }

    try {
      const res = await fetch("/api/web-import/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      console.log("调用 /api/web-import/parse，status =", res.status);
      if (!res.ok) {
        const errData = await res.json().catch(() => null);
        const msg =
          (errData && errData.detail) ||
          "解析失败（status=" + res.status + "）";
        alert(msg);
        renderErrorPreview(msg);  // 在页面右侧显示失败原因
        return;
      }
      const parsed = await res.json();
      console.log("解析结果：", parsed);
      renderParsedPreview(parsed);
    } catch (e) {
      console.error("解析失败：", e);
      const msg = "解析失败，请检查链接是否可访问";
      alert(msg);
      renderErrorPreview(msg);
    } finally {
      if (parseBtn) {
        parseBtn.disabled = false;
        parseBtn.textContent = "解析项目";
      }
    }
  }

  if (parseBtn) {
    console.log("找到解析按钮 import-parse-btn，绑定 click 事件");
    parseBtn.addEventListener("click", handleParseClick);
  } else {
    console.warn("未找到 #import-parse-btn 按钮，检查 web-import.html 中的 id");
  }

  if (urlInput) {
    urlInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        handleParseClick();
      }
    });
  }

  // 初始化：填充支持网站 + 空预览
  fillSupportedSitesStatic();
  renderEmptyPreview();
});
