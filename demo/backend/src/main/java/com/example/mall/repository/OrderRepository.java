package com.example.mall.repository;

import com.example.mall.entity.Order;
import com.example.mall.entity.OrderItem;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.PreparedStatement;
import java.util.List;

/**
 * 订单数据访问(H2 + JdbcTemplate)
 */
@Repository
public class OrderRepository {

    private final JdbcTemplate jdbc;

    @Autowired
    public OrderRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Order> ORDER_MAPPER = (rs, i) -> {
        Order o = new Order();
        o.setId(rs.getLong("id"));
        o.setOrderNo(rs.getString("order_no"));
        o.setUserId(rs.getLong("user_id"));
        o.setTotalAmount(rs.getBigDecimal("total_amount"));
        o.setDiscountPoints(rs.getInt("discount_points"));
        o.setDiscountAmount(rs.getBigDecimal("discount_amount"));
        o.setActualAmount(rs.getBigDecimal("actual_amount"));
        o.setStatus(rs.getString("status"));
        o.setReceiver(rs.getString("receiver"));
        o.setPhone(rs.getString("phone"));
        o.setAddress(rs.getString("address"));
        o.setCreatedAt(rs.getObject("created_at") == null ? null : rs.getTimestamp("created_at").toString());
        o.setPaidAt(rs.getObject("paid_at") == null ? null : rs.getTimestamp("paid_at").toString());
        o.setShippedAt(rs.getObject("shipped_at") == null ? null : rs.getTimestamp("shipped_at").toString());
        o.setCompletedAt(rs.getObject("completed_at") == null ? null : rs.getTimestamp("completed_at").toString());
        return o;
    };

    private static final RowMapper<OrderItem> ITEM_MAPPER = (rs, i) -> {
        OrderItem item = new OrderItem();
        item.setId(rs.getLong("id"));
        item.setOrderId(rs.getLong("order_id"));
        item.setProductId(rs.getLong("product_id"));
        item.setProductName(rs.getString("product_name"));
        item.setPrice(rs.getBigDecimal("price"));
        item.setQuantity(rs.getInt("quantity"));
        item.setReviewed(rs.getBoolean("reviewed"));
        return item;
    };

    public Long insertOrder(Order o) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(conn -> {
            PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO mall_order (order_no, user_id, total_amount, discount_points, discount_amount, " +
                            "actual_amount, status, receiver, phone, address) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    new String[]{"id"});
            ps.setString(1, o.getOrderNo());
            ps.setLong(2, o.getUserId());
            ps.setBigDecimal(3, o.getTotalAmount());
            ps.setInt(4, o.getDiscountPoints());
            ps.setBigDecimal(5, o.getDiscountAmount());
            ps.setBigDecimal(6, o.getActualAmount());
            ps.setString(7, o.getStatus());
            ps.setString(8, o.getReceiver());
            ps.setString(9, o.getPhone());
            ps.setString(10, o.getAddress());
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? null : key.longValue();
    }

    public int insertOrderItem(Long orderId, OrderItem item) {
        return jdbc.update("INSERT INTO order_item (order_id, product_id, product_name, price, quantity, reviewed) " +
                        "VALUES (?, ?, ?, ?, ?, FALSE)",
                orderId, item.getProductId(), item.getProductName(), item.getPrice(), item.getQuantity());
    }

    public Order findOrderById(Long id) {
        List<Order> list = jdbc.query("SELECT * FROM mall_order WHERE id = ?", ORDER_MAPPER, id);
        return list.isEmpty() ? null : list.get(0);
    }

    /** 我的订单列表,status 为空则全部 */
    public List<Order> listByUser(Long userId, String status) {
        if (status == null || status.isBlank()) {
            return jdbc.query("SELECT * FROM mall_order WHERE user_id = ? ORDER BY id DESC", ORDER_MAPPER, userId);
        }
        return jdbc.query("SELECT * FROM mall_order WHERE user_id = ? AND status = ? ORDER BY id DESC",
                ORDER_MAPPER, userId, status);
    }

    /** 管理端:全部订单(JOIN 用户昵称/邮箱),支持 status、keyword(订单号/昵称/邮箱模糊)与时间范围(startDate/endDate,yyyy-MM-dd) */
    private static final RowMapper<Order> ADMIN_ORDER_MAPPER = (rs, i) -> {
        Order o = ORDER_MAPPER.mapRow(rs, i);
        o.setUserNickname(rs.getString("user_nickname"));
        o.setUserEmail(rs.getString("user_email"));
        return o;
    };

    public List<Order> listAll(String status, String keyword, String startDate, String endDate) {
        String sql = "SELECT o.*, u.nickname AS user_nickname, u.email AS user_email " +
                "FROM mall_order o JOIN app_user u ON o.user_id = u.id ";
        StringBuilder where = new StringBuilder();
        Object[] args = new Object[6]; // status(1) + keyword(3) + startDate(1) + endDate(1)
        int n = 0;
        if (status != null && !status.isBlank()) {
            where.append(n > 0 ? " AND " : " WHERE ").append("o.status = ?");
            args[n++] = status;
        }
        if (keyword != null && !keyword.isBlank()) {
            where.append(n > 0 ? " AND " : " WHERE ")
                    .append("(o.order_no LIKE ? OR u.nickname LIKE ? OR u.email LIKE ?)");
            String like = "%" + keyword.trim() + "%";
            args[n++] = like;
            args[n++] = like;
            args[n++] = like;
        }
        if (startDate != null && !startDate.isBlank()) {
            where.append(n > 0 ? " AND " : " WHERE ")
                    .append("o.created_at >= PARSEDATETIME(?, 'yyyy-MM-dd')");
            args[n++] = startDate.trim();
        }
        if (endDate != null && !endDate.isBlank()) {
            where.append(n > 0 ? " AND " : " WHERE ")
                    .append("o.created_at < PARSEDATETIME(?, 'yyyy-MM-dd') + 1 DAY");
            args[n++] = endDate.trim();
        }
        String sqlFinal = sql + where + " ORDER BY o.id DESC";
        if (n == 0) {
            return jdbc.query(sqlFinal, ADMIN_ORDER_MAPPER);
        }
        Object[] param = new Object[n];
        System.arraycopy(args, 0, param, 0, n);
        return jdbc.query(sqlFinal, ADMIN_ORDER_MAPPER, param);
    }

    /** 管理端:按 ID 查询单个订单(JOIN 用户昵称/邮箱) */
    public Order findAdminOrderById(Long id) {
        List<Order> list = jdbc.query(
                "SELECT o.*, u.nickname AS user_nickname, u.email AS user_email " +
                        "FROM mall_order o JOIN app_user u ON o.user_id = u.id WHERE o.id = ?",
                ADMIN_ORDER_MAPPER, id);
        return list.isEmpty() ? null : list.get(0);
    }

    public List<OrderItem> findItemsByOrderId(Long orderId) {
        return jdbc.query("SELECT * FROM order_item WHERE order_id = ? ORDER BY id", ITEM_MAPPER, orderId);
    }

    public OrderItem findOrderItemById(Long id) {
        List<OrderItem> list = jdbc.query("SELECT * FROM order_item WHERE id = ?", ITEM_MAPPER, id);
        return list.isEmpty() ? null : list.get(0);
    }

    public int markOrderItemReviewed(Long orderItemId) {
        return jdbc.update("UPDATE order_item SET reviewed = TRUE WHERE id = ?", orderItemId);
    }

    public int markPaid(Long orderId) {
        return jdbc.update("UPDATE mall_order SET status = 'PAID', paid_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'PENDING_PAYMENT'", orderId);
    }

    public int markShipped(Long orderId) {
        return jdbc.update("UPDATE mall_order SET status = 'SHIPPED', shipped_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'PAID'", orderId);
    }

    public int markCompleted(Long orderId) {
        return jdbc.update("UPDATE mall_order SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'SHIPPED'", orderId);
    }

    public int markCancelled(Long orderId) {
        return jdbc.update("UPDATE mall_order SET status = 'CANCELLED' WHERE id = ? AND status = 'PENDING_PAYMENT'", orderId);
    }
}
