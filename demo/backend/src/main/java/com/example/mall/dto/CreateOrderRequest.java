package com.example.mall.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;

import java.util.List;

/**
 * 创建订单请求(从购物车结算)
 * cartItemIds: 选中的购物车项 ID 列表
 * usePoints:   使用的积分数量(10 积分 = 1 元)
 */
public class CreateOrderRequest {

    @NotEmpty(message = "请选择要结算的商品")
    private List<Long> cartItemIds;

    @NotNull(message = "积分数量不能为空")
    @PositiveOrZero(message = "积分数量不能为负")
    private Integer usePoints;

    @NotBlank(message = "收货人不能为空")
    private String receiver;

    @NotBlank(message = "联系电话不能为空")
    private String phone;

    @NotBlank(message = "收货地址不能为空")
    private String address;

    public List<Long> getCartItemIds() {
        return cartItemIds;
    }

    public void setCartItemIds(List<Long> cartItemIds) {
        this.cartItemIds = cartItemIds;
    }

    public Integer getUsePoints() {
        return usePoints;
    }

    public void setUsePoints(Integer usePoints) {
        this.usePoints = usePoints;
    }

    public String getReceiver() {
        return receiver;
    }

    public void setReceiver(String receiver) {
        this.receiver = receiver;
    }

    public String getPhone() {
        return phone;
    }

    public void setPhone(String phone) {
        this.phone = phone;
    }

    public String getAddress() {
        return address;
    }

    public void setAddress(String address) {
        this.address = address;
    }
}
