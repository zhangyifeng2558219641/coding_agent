package com.example.mall.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * 商品状态请求(上/下架)
 */
public class StatusRequest {

    @NotBlank(message = "status 不能为空")
    private String status;

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
