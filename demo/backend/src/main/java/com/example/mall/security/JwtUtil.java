package com.example.mall.security;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

/**
 * 轻量 JWT 工具(HS256),仅依赖 JDK,用于演示。
 * payload 携带 userId(username)、role,便于拦截器判断管理员。
 */
public final class JwtUtil {

    /** 演示用密钥,生产环境应放入配置且足够随机 */
    private static final String SECRET = "mall-secret-key-please-change-in-production";

    /** Token 有效期(秒): 12 小时 */
    private static final long EXPIRE_SECONDS = 12 * 60 * 60L;

    private static final String HMAC_ALG = "HmacSHA256";

    private JwtUtil() {
    }

    /** 生成 token */
    public static String generate(Long userId, String username, String role) {
        String header = b64Url("{\"alg\":\"HS256\",\"typ\":\"JWT\"}");
        long now = System.currentTimeMillis() / 1000;
        String payload = b64Url("{\"sub\":" + userId
                + ",\"name\":\"" + username
                + "\",\"role\":\"" + role
                + "\",\"iat\":" + now
                + ",\"exp\":" + (now + EXPIRE_SECONDS) + "}");
        String data = header + "." + payload;
        return data + "." + hmacSha256(data);
    }

    /** 校验 token 并返回用户 id;非法或过期抛出异常 */
    public static Long parse(String token) {
        return (Long) parsePayload(token, "sub");
    }

    /** 从 token 中解析 role */
    public static String getRole(String token) {
        return (String) parsePayload(token, "role");
    }

    /** 解析 payload 中指定字段(仅支持数值与字符串) */
    private static Object parsePayload(String token, String key) {
        String[] parts = token.split("\\.");
        if (parts.length != 3) {
            throw new IllegalArgumentException("Token 格式错误");
        }
        String data = parts[0] + "." + parts[1];

        // 1. 校验签名
        String expected = hmacSha256(data);
        if (!MessageDigest.isEqual(expected.getBytes(StandardCharsets.UTF_8),
                parts[2].getBytes(StandardCharsets.UTF_8))) {
            throw new IllegalArgumentException("Token 签名校验失败");
        }

        // 2. 解析 payload,校验过期时间
        String payloadJson = new String(Base64.getUrlDecoder().decode(parts[1]), StandardCharsets.UTF_8);
        long exp = Long.parseLong(extractField(payloadJson, "exp"));
        if (exp < System.currentTimeMillis() / 1000) {
            throw new IllegalArgumentException("Token 已过期");
        }
        String raw = extractField(payloadJson, key);
        if ("sub".equals(key)) {
            return Long.parseLong(raw);
        }
        // role 字段是字符串,strip 引号
        return raw.replace("\"", "");
    }

    /** base64url 编码(不带 padding) */
    private static String b64Url(String json) {
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString(json.getBytes(StandardCharsets.UTF_8));
    }

    /** HMAC-SHA256 签名(base64url) */
    private static String hmacSha256(String data) {
        try {
            Mac mac = Mac.getInstance(HMAC_ALG);
            mac.init(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), HMAC_ALG));
            return Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(mac.doFinal(data.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("HMAC 计算失败", e);
        }
    }

    /** 从扁平 JSON 中提取字段(演示用) */
    private static String extractField(String json, String key) {
        String marker = "\"" + key + "\":";
        int start = json.indexOf(marker);
        if (start < 0) {
            throw new IllegalArgumentException("Token 缺少字段: " + key);
        }
        start += marker.length();
        int end = json.indexOf(',', start);
        if (end < 0) {
            end = json.indexOf('}', start);
        }
        if (end < 0) {
            throw new IllegalArgumentException("Token payload 解析失败");
        }
        return json.substring(start, end).trim();
    }
}
