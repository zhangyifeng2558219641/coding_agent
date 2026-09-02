package com.example.mall.entity;

/**
 * 积分流水实体(point_record)
 * type: GAIN(获得) / SPEND(使用) / ADMIN(管理员调整)
 */
public class PointRecord {

    private Long id;
    private Long userId;
    private String type;
    /** 变动数量:正为获得,负为扣减 */
    private Integer points;
    /** 变动后余额快照 */
    private Integer balance;
    private Long orderId;
    private String remark;
    private String createdAt;

    public PointRecord() {
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getUserId() {
        return userId;
    }

    public void setUserId(Long userId) {
        this.userId = userId;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public Integer getPoints() {
        return points;
    }

    public void setPoints(Integer points) {
        this.points = points;
    }

    public Integer getBalance() {
        return balance;
    }

    public void setBalance(Integer balance) {
        this.balance = balance;
    }

    public Long getOrderId() {
        return orderId;
    }

    public void setOrderId(Long orderId) {
        this.orderId = orderId;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }

    public String getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(String createdAt) {
        this.createdAt = createdAt;
    }
}
