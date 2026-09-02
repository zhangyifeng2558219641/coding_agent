package com.example.mall.entity;

import java.math.BigDecimal;
import java.util.List;

/**
 * 订单实体(mall_order)
 * 状态机: PENDING_PAYMENT(待支付) -> PAID(已支付/待发货) -> SHIPPED(已发货/待收货) -> COMPLETED(已完成)
 *         PENDING_PAYMENT -> CANCELLED(已取消)
 */
public class Order {

    private Long id;
    private String orderNo;
    private Long userId;
    private BigDecimal totalAmount;    // 应付金额(商品小计)
    private Integer discountPoints;    // 使用积分数量
    private BigDecimal discountAmount; // 积分抵扣金额
    private BigDecimal actualAmount;   // 实付金额
    private String status;
    private String receiver;
    private String phone;
    private String address;
    private String createdAt;
    private String paidAt;
    private String shippedAt;
    private String completedAt;

    /** 用户昵称/邮箱(管理端 JOIN 查询填充,非表字段) */
    private String userNickname;
    private String userEmail;

    /** 订单明细(查询详情时填充,非表字段) */
    private List<OrderItem> items;

    public Order() {
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getOrderNo() {
        return orderNo;
    }

    public void setOrderNo(String orderNo) {
        this.orderNo = orderNo;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(BigDecimal totalAmount) {
        this.totalAmount = totalAmount;
    }

    public Integer getDiscountPoints() {
        return discountPoints;
    }

    public void setDiscountPoints(Integer discountPoints) {
        this.discountPoints = discountPoints;
    }

    public BigDecimal getDiscountAmount() {
        return discountAmount;
    }

    public void setDiscountAmount(BigDecimal discountAmount) {
        this.discountAmount = discountAmount;
    }

    public BigDecimal getActualAmount() {
        return actualAmount;
    }

    public void setActualAmount(BigDecimal actualAmount) {
        this.actualAmount = actualAmount;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
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

    public String getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(String createdAt) {
        this.createdAt = createdAt;
    }

    public String getPaidAt() {
        return paidAt;
    }

    public void setPaidAt(String paidAt) {
        this.paidAt = paidAt;
    }

    public String getShippedAt() {
        return shippedAt;
    }

    public void setShippedAt(String shippedAt) {
        this.shippedAt = shippedAt;
    }

    public String getCompletedAt() {
        return completedAt;
    }

    public void setCompletedAt(String completedAt) {
        this.completedAt = completedAt;
    }

    public List<OrderItem> getItems() {
        return items;
    }

    public void setItems(List<OrderItem> items) {
        this.items = items;
    }

    public String getUserNickname() {
        return userNickname;
    }

    public void setUserNickname(String userNickname) {
        this.userNickname = userNickname;
    }

    public String getUserEmail() {
        return userEmail;
    }

    public void setUserEmail(String userEmail) {
        this.userEmail = userEmail;
    }
}
